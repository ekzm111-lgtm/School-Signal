import os
import uuid
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pydantic import BaseModel
import winsound

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from supertonic import TTS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

# 1. 로깅 및 폴더 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

DATA_FILE = os.path.join(BASE_DIR, "schedule.json")

# 2. TTS 엔진 싱글톤 래퍼
class TTSEngine:
    def __init__(self):
        logger.info("Initializing Supertonic TTS engine...")
        self.tts = TTS(auto_download=True)
        self.lock = threading.Lock()
        logger.info("Supertonic TTS engine initialized.")

    def get_voice_style(self, voice_name: str = "F1"):
        try:
            return self.tts.get_voice_style(voice_name)
        except Exception:
            # Fallback to M1 if requested name fails, or F1
            try:
                return self.tts.get_voice_style("M1")
            except Exception:
                return self.tts.get_voice_style("F1")

    def synthesize_to_file(self, text: str, output_path: str, voice_name: str = "F1") -> float:
        with self.lock:
            try:
                style = self.get_voice_style(voice_name)
                # 한국어(ko)로 음성 합성
                wav, duration = self.tts.synthesize(text, voice_style=style, lang="ko")
                self.tts.save_audio(wav, output_path)
                return float(duration.item())
            except Exception as e:
                logger.error(f"TTS synthesis failed: {e}")
                raise e

# 전역 TTS 및 Scheduler 인스턴스
tts_engine = None
scheduler = BackgroundScheduler()

# 3. 데이터 모델 정의
class CustomTemplates(BaseModel):
    # offset분에 대한 커스텀 템플릿 딕셔너리 (예: {"10": "10분 전 안내...", "5": "..."})
    templates: Dict[str, str]

class ScheduleRequest(BaseModel):
    exam_name: str
    end_time: str  # HH:MM format
    offsets: List[int]  # [10, 5, 1, 0] 등 (0은 종료 시점)
    voice_name: str = "F1"
    custom_templates: Optional[Dict[str, str]] = None  # key: str(offset), value: text

# 4. JSON 데이터 퍼시스턴스 관리
def load_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {"schedules": [], "logs": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read data file: {e}")
        return {"schedules": [], "logs": []}

def save_data(data: Dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write data file: {e}")

# 5. 오디오 동기식 단일 재생을 위한 락
play_lock = threading.Lock()

def play_audio(audio_path: str):
    """
    백그라운드 스케줄러 스레드에서 동기적으로 재생을 수행하여,
    여러 방송이 동시에 재생되지 않고 락을 대기하도록 처리합니다.
    """
    with play_lock:
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return False
        try:
            logger.info(f"Playing audio: {audio_path}")
            # SND_FILENAME 플래그는 동기식(끝날때까지 대기) 재생입니다.
            winsound.PlaySound(audio_path, winsound.SND_FILENAME)
            logger.info(f"Playback completed: {audio_path}")
            return True
        except Exception as e:
            logger.error(f"Winsound play error: {e}")
            return False

# 스케줄러가 트리거할 실제 작업
def run_broadcast_job(schedule_id: str, broadcast_id: str):
    logger.info(f"Triggered broadcast job: Schedule={schedule_id}, Broadcast={broadcast_id}")
    data = load_data()
    
    # 1. 스케줄 및 방송 정보 찾기
    target_schedule = None
    target_broadcast = None
    for s in data["schedules"]:
        if s["id"] == schedule_id:
            target_schedule = s
            for b in s["broadcasts"]:
                if b["id"] == broadcast_id:
                    target_broadcast = b
                    break
            break
            
    if not target_schedule or not target_broadcast:
        logger.error("Schedule or Broadcast not found in data.")
        return

    # 2. 상태를 playing으로 업데이트
    target_broadcast["status"] = "playing"
    save_data(data)

    # 3. 재생
    audio_path = target_broadcast["audio_path"]
    success = play_audio(audio_path)

    # 4. 결과 업데이트 및 로그 기록
    data = load_data() # 최신본 로드
    # 다시 객체 찾기
    for s in data["schedules"]:
        if s["id"] == schedule_id:
            for b in s["broadcasts"]:
                if b["id"] == broadcast_id:
                    b["status"] = "completed" if success else "failed"
                    break
            break

    # 로그 기록 추가
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exam_name": target_schedule["exam_name"],
        "broadcast_type": f"{target_broadcast['offset_minutes']}분 전 안내" if target_broadcast['offset_minutes'] > 0 else "시험 종료 안내",
        "text": target_broadcast["text"],
        "status": "success" if success else "failed"
    }
    data["logs"].insert(0, log_entry) # 최신 로그가 맨 위로 오도록 함
    save_data(data)

# 6. FastAPI 서버 정의
app = FastAPI(title="시험 시간 자동 송출 시스템")

# CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 7. 시작 및 종료 이벤트 처리
@app.on_event("startup")
def startup_event():
    global tts_engine
    tts_engine = TTSEngine()
    
    # 스케줄러 시작
    scheduler.start()
    logger.info("Scheduler started.")
    
    # 서버 재시작 시, 기존 보관된 스케줄 중 pending 상태이고 
    # 아직 실행 시각이 지나지 않은 항목들을 다시 스케줄러에 등록
    data = load_data()
    now = datetime.now()
    active_jobs_count = 0
    
    for s in data["schedules"]:
        for b in s["broadcasts"]:
            if b["status"] == "pending":
                trigger_time = datetime.strptime(b["trigger_time"], "%Y-%m-%d %H:%M:%S")
                if trigger_time > now:
                    scheduler.add_job(
                        run_broadcast_job,
                        trigger=DateTrigger(run_date=trigger_time),
                        args=[s["id"], b["id"]],
                        id=b["id"]
                    )
                    active_jobs_count += 1
                else:
                    # 시간이 이미 지난 pending 항목은 만료 처리
                    b["status"] = "expired"
                    
    save_data(data)
    logger.info(f"Restored {active_jobs_count} pending broadcast jobs in scheduler.")

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler shutdown.")

# 8. REST API 라우트 정의

@app.get("/api/voices")
def get_voices():
    # 기본 제공되는 대표적인 목소리 스타일 목록
    return [
        {"id": "F1", "name": "여성 1 (F1 - 차분함)"},
        {"id": "F2", "name": "여성 2 (F2 - 부드러움)"},
        {"id": "M1", "name": "남성 1 (M1 - 신뢰감)"},
        {"id": "M2", "name": "남성 2 (M2 - 묵직함)"}
    ]

@app.get("/api/schedule")
def get_schedules():
    data = load_data()
    # 과거 지난 일정을 필터링하거나 정리하진 않고 전체를 보냅니다.
    # 클라이언트에서 알아서 가공합니다.
    return data["schedules"]

@app.post("/api/schedule")
def add_schedule(req: ScheduleRequest):
    global tts_engine
    if not tts_engine:
        raise HTTPException(status_code=500, detail="TTS 엔진이 아직 초기화되지 않았습니다.")

    # 1. 시험 시간 파싱
    now_date = datetime.now().date()
    try:
        end_time_parsed = datetime.strptime(req.end_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력하세요.")
        
    exam_end_datetime = datetime.combine(now_date, end_time_parsed)
    
    # 만약 현재 시각보다 설정된 시험 종료 시간이 이전이라면 다음날로 설정할 것인지 검증
    # (예: 현재 17:00인데 10:00으로 설정하면 내일 시험으로 간주)
    if exam_end_datetime < datetime.now():
        exam_end_datetime += timedelta(days=1)

    schedule_id = str(uuid.uuid4())
    broadcasts = []
    
    # 2. 각 offset별로 멘트 텍스트 구성 및 TTS 음원 사전 생성
    for offset in req.offsets:
        trigger_time = exam_end_datetime - timedelta(minutes=offset)
        
        # 현재 시각보다 이전 시점인 경우 등록 스킵
        if trigger_time <= datetime.now():
            logger.warning(f"Skip offset {offset}m for {req.exam_name} because it is in the past: {trigger_time}")
            continue

        # 템플릿 생성
        custom_text = req.custom_templates.get(str(offset)) if req.custom_templates else None
        
        if custom_text and custom_text.strip():
            text = custom_text.strip()
        else:
            if offset > 0:
                text = f"아 아, 시험 종료 안내 말씀 드립니다. 잠시 후 {req.exam_name} 시험 종료 {offset}분 전입니다. 수험생 여러분께서는 답안 마킹을 다시 한번 확인하시기 바랍니다."
            else:
                text = f"아 아, 시험 종료 안내 말씀 드립니다. {req.exam_name} 시험 시간이 모두 종료되었습니다. 수험생 여러분께서는 필기도구를 내려놓으시고 답안지를 제출해 주시기 바랍니다."

        broadcast_id = str(uuid.uuid4())
        audio_filename = f"{schedule_id}_{offset}.wav"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        
        # TTS 사전 합성 실행 (정시 플레이 시의 딜레이를 방지하기 위함)
        try:
            logger.info(f"Pre-synthesizing TTS for offset {offset}m: '{text}'")
            duration = tts_engine.synthesize_to_file(text, audio_path, req.voice_name)
        except Exception as e:
            logger.error(f"TTS Pre-synthesis failed for offset {offset}: {e}")
            raise HTTPException(status_code=500, detail=f"TTS 음성 합성 중 오류가 발생했습니다: {str(e)}")

        broadcasts.append({
            "id": broadcast_id,
            "offset_minutes": offset,
            "trigger_time": trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "audio_path": audio_path,
            "duration": duration,
            "status": "pending"
        })

    if not broadcasts:
        raise HTTPException(status_code=400, detail="설정된 모든 안내 시점이 이미 지난 시간입니다.")

    # 3. 스케줄러에 등록
    for b in broadcasts:
        trigger_time = datetime.strptime(b["trigger_time"], "%Y-%m-%d %H:%M:%S")
        scheduler.add_job(
            run_broadcast_job,
            trigger=DateTrigger(run_date=trigger_time),
            args=[schedule_id, b["id"]],
            id=b["id"]
        )

    # 4. JSON 데이터에 저장
    new_schedule = {
        "id": schedule_id,
        "exam_name": req.exam_name,
        "end_time": exam_end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "voice_name": req.voice_name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "broadcasts": broadcasts
    }

    data = load_data()
    data["schedules"].append(new_schedule)
    save_data(data)

    logger.info(f"Successfully added schedule {schedule_id} for {req.exam_name} with {len(broadcasts)} broadcasts.")
    return new_schedule

@app.delete("/api/schedule/{id}")
def delete_schedule(id: str):
    data = load_data()
    target_idx = -1
    for idx, s in enumerate(data["schedules"]):
        if s["id"] == id:
            target_idx = idx
            break
            
    if target_idx == -1:
        raise HTTPException(status_code=404, detail="해당 일정을 찾을 수 없습니다.")

    target_schedule = data["schedules"][target_idx]
    
    # 1. 스케줄러에서 등록된 작업 취소 및 관련 오디오 파일 삭제
    for b in target_schedule["broadcasts"]:
        if b["status"] == "pending":
            try:
                scheduler.remove_job(b["id"])
                logger.info(f"Removed job {b['id']} from scheduler.")
            except Exception:
                logger.warning(f"Job {b['id']} was not found in scheduler or already executed.")
        
        # 오디오 파일 정리
        if os.path.exists(b["audio_path"]):
            try:
                os.remove(b["audio_path"])
                logger.info(f"Removed audio file: {b['audio_path']}")
            except Exception as e:
                logger.warning(f"Failed to delete audio file {b['audio_path']}: {e}")

    # 2. JSON 데이터에서 제거
    data["schedules"].pop(target_idx)
    save_data(data)
    
    return {"message": "일정이 성공적으로 삭제되었습니다."}

@app.post("/api/schedule/play_now")
def play_now(req: Dict, background_tasks: BackgroundTasks):
    global tts_engine
    if not tts_engine:
        raise HTTPException(status_code=500, detail="TTS 엔진이 아직 초기화되지 않았습니다.")
        
    text = req.get("text", "").strip()
    voice_name = req.get("voice_name", "F1")
    
    if not text:
        raise HTTPException(status_code=400, detail="재생할 텍스트가 비어 있습니다.")

    # 즉시 재생용 파일 생성
    temp_id = str(uuid.uuid4())
    audio_path = os.path.join(AUDIO_DIR, f"immediate_{temp_id}.wav")
    
    try:
        # TTS 생성
        tts_engine.synthesize_to_file(text, audio_path, voice_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 음성 합성 중 오류가 발생했습니다: {str(e)}")

    # 백그라운드 태스크로 재생하여 API 응답은 즉시 반환
    def play_and_cleanup():
        play_success = play_audio(audio_path)
        # 재생 완료 후 파일 자동 삭제
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass
        
        # 로그 기록
        data = load_data()
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exam_name": "즉시 수동 방송",
            "broadcast_type": "수동 송출",
            "text": text,
            "status": "success" if play_success else "failed"
        }
        data["logs"].insert(0, log_entry)
        save_data(data)

    background_tasks.add_task(play_and_cleanup)
    return {"message": "즉시 방송 송출이 시작되었습니다."}

@app.post("/api/tts/preview")
def tts_preview(req: Dict):
    global tts_engine
    if not tts_engine:
        raise HTTPException(status_code=500, detail="TTS 엔진이 아직 초기화되지 않았습니다.")

    text = req.get("text", "").strip()
    voice_name = req.get("voice_name", "F1")
    
    if not text:
        raise HTTPException(status_code=400, detail="텍스트가 비어 있습니다.")

    temp_id = str(uuid.uuid4())
    preview_path = os.path.join(AUDIO_DIR, f"preview_{temp_id}.wav")
    
    try:
        # TTS 파일 생성
        tts_engine.synthesize_to_file(text, preview_path, voice_name)
        
        # 브라우저 전송용 스트림 반환
        def iterfile():
            with open(preview_path, mode="rb") as file_like:
                yield from file_like
            
            # 전송 완료 후 백그라운드에서 임시 파일 삭제
            try:
                os.remove(preview_path)
            except Exception as e:
                logger.warning(f"Failed to delete preview file: {e}")

        return StreamingResponse(iterfile(), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 음성 합성 중 오류가 발생했습니다: {str(e)}")

@app.get("/api/logs")
def get_logs():
    data = load_data()
    return data["logs"]

# 9. 정적 파일 및 메인 페이지 라우트 서빙
static_path = os.path.join(BASE_DIR, "static")
os.makedirs(static_path, exist_ok=True)

# index.html 직접 제공
@app.get("/")
def read_index():
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "시스템 준비 중입니다. static 폴더의 index.html이 존재하는지 확인해 주세요."}

# static 하위의 css, js 등 서빙
app.mount("/static", StaticFiles(directory=static_path), name="static")

if __name__ == "__main__":
    import uvicorn
    # uvicorn.run을 통해 로컬 호스트 8000포트로 실행
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
