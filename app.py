import os
import uuid
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from supertonic import TTS
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
        # 비동기 세션 내 동기 락 처리
        import threading
        self.lock = threading.Lock()
        logger.info("Supertonic TTS engine initialized.")

    def get_voice_style(self, voice_name: str = "F1"):
        try:
            return self.tts.get_voice_style(voice_name)
        except Exception:
            try:
                return self.tts.get_voice_style("M1")
            except Exception:
                return self.tts.get_voice_style("F1")

    def synthesize_to_file(self, text: str, output_path: str, voice_name: str = "F1") -> float:
        with self.lock:
            try:
                style = self.get_voice_style(voice_name)
                wav, duration = self.tts.synthesize(text, voice_style=style, lang="ko")
                self.tts.save_audio(wav, output_path)
                return float(duration.item())
            except Exception as e:
                logger.error(f"TTS synthesis failed: {e}")
                raise e

# 전역 변수들
tts_engine = None
scheduler = AsyncIOScheduler()
connected_clients: List[asyncio.Queue] = []

# 3. 데이터 모델 정의
class ScheduleRequest(BaseModel):
    exam_name: str
    end_time: str  # HH:MM format
    offsets: List[int]
    voice_name: str = "F1"
    custom_templates: Optional[Dict[str, str]] = None

# 4. JSON 데이터 관리
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

# 5. 브라우저 송출 브로드캐스팅
async def broadcast_play_signal(audio_url: str, text: str, schedule_id: str, broadcast_id: str, exam_name: str, broadcast_type: str):
    """
    모든 연결된 웹 화면(SSE)으로 오디오 재생 신호를 전송합니다.
    """
    payload = {
        "audio_url": audio_url,
        "text": text,
        "schedule_id": schedule_id,
        "broadcast_id": broadcast_id,
        "exam_name": exam_name,
        "broadcast_type": broadcast_type
    }
    logger.info(f"Broadcasting play signal to {len(connected_clients)} clients for: {text}")
    
    # 각 클라이언트 대기 큐에 신호 전달
    for queue in connected_clients:
        await queue.put(payload)

# 스케줄러가 예약 시각에 실행할 비동기 작업
async def run_broadcast_job(schedule_id: str, broadcast_id: str):
    logger.info(f"Triggered scheduler job: Schedule={schedule_id}, Broadcast={broadcast_id}")
    data = load_data()
    
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
        logger.error("Schedule or Broadcast not found in database.")
        return

    # 1. 상태를 playing으로 임시 마킹
    target_broadcast["status"] = "playing"
    save_data(data)

    # 2. 브라우저에 오디오 파일 재생 신호 송출 (SSE)
    # 파일명 추출 및 외부 경로 서빙용 URL 구성
    audio_filename = os.path.basename(target_broadcast["audio_path"])
    audio_url = f"/api/audio/{audio_filename}"
    
    broadcast_type = f"{target_broadcast['offset_minutes']}분 전 안내" if target_broadcast['offset_minutes'] > 0 else "시험 종료 안내"
    
    # 비동기로 모든 브라우저 클라이언트에 오디오 전송
    await broadcast_play_signal(
        audio_url=audio_url,
        text=target_broadcast["text"],
        schedule_id=schedule_id,
        broadcast_id=broadcast_id,
        exam_name=target_schedule["exam_name"],
        broadcast_type=broadcast_type
    )

    # 3. 송출 상태를 완료로 업데이트하고 로그 기록
    # (브라우저가 신호를 수신해 실제 물리적인 사운드 칩으로 재생하므로, 서버단에서는 전송 완료 시점을 완료로 처리)
    data = load_data()
    for s in data["schedules"]:
        if s["id"] == schedule_id:
            for b in s["broadcasts"]:
                if b["id"] == broadcast_id:
                    b["status"] = "completed"
                    break
            break

    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exam_name": target_schedule["exam_name"],
        "broadcast_type": broadcast_type,
        "text": target_broadcast["text"],
        "status": "success"
    }
    data["logs"].insert(0, log_entry)
    save_data(data)

# 6. FastAPI 서버 정의
app = FastAPI(title="시험 시간 자동 송출 시스템 (브라우저 출력용)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    global tts_engine
    tts_engine = TTSEngine()
    
    # 비동기 스케줄러 기동
    scheduler.start()
    logger.info("Async Scheduler started.")
    
    # 대기 중인 스케줄 복구
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
                    b["status"] = "expired"
                    
    save_data(data)
    logger.info(f"Restored {active_jobs_count} pending broadcast jobs in async scheduler.")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler shutdown.")

# 7. REST API 라우트 정의

@app.get("/api/voices")
def get_voices():
    return [
        {"id": "F1", "name": "여성 1 (F1 - 차분함)"},
        {"id": "F2", "name": "여성 2 (F2 - 부드러움)"},
        {"id": "M1", "name": "남성 1 (M1 - 신뢰감)"},
        {"id": "M2", "name": "남성 2 (M2 - 묵직함)"}
    ]

@app.get("/api/schedule")
def get_schedules():
    data = load_data()
    return data["schedules"]

@app.post("/api/schedule")
def add_schedule(req: ScheduleRequest):
    global tts_engine
    if not tts_engine:
        raise HTTPException(status_code=500, detail="TTS 엔진이 아직 초기화되지 않았습니다.")

    now_date = datetime.now().date()
    try:
        end_time_parsed = datetime.strptime(req.end_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력하세요.")
        
    exam_end_datetime = datetime.combine(now_date, end_time_parsed)
    
    if exam_end_datetime < datetime.now():
        exam_end_datetime += timedelta(days=1)

    schedule_id = str(uuid.uuid4())
    broadcasts = []
    
    for offset in req.offsets:
        trigger_time = exam_end_datetime - timedelta(minutes=offset)
        
        if trigger_time <= datetime.now():
            logger.warning(f"Skip offset {offset}m for {req.exam_name} because it is in the past: {trigger_time}")
            continue

        custom_text = req.custom_templates.get(str(offset)) if req.custom_templates else None
        
        if custom_text and custom_text.strip():
            text = custom_text.strip()
        else:
            if offset > 0:
                text = f"시험 종료 안내 말씀 드립니다. 잠시 후 {req.exam_name} 시험 종료 {offset}분 전입니다. 수험생 여러분께서는 답안 마킹을 다시 한번 확인하시기 바랍니다."
            else:
                text = f"시험 종료 안내 말씀 드립니다. {req.exam_name} 시험 시간이 모두 종료되었습니다. 수험생 여러분께서는 필기도구를 내려놓으시고 답안지를 제출해 주시기 바랍니다."

        broadcast_id = str(uuid.uuid4())
        audio_filename = f"{schedule_id}_{offset}.wav"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        
        # TTS 사전 합성
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

    # 스케줄러에 비동기 작업으로 추가
    for b in broadcasts:
        trigger_time = datetime.strptime(b["trigger_time"], "%Y-%m-%d %H:%M:%S")
        scheduler.add_job(
            run_broadcast_job,
            trigger=DateTrigger(run_date=trigger_time),
            args=[schedule_id, b["id"]],
            id=b["id"]
        )

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
    
    for b in target_schedule["broadcasts"]:
        if b["status"] == "pending":
            try:
                scheduler.remove_job(b["id"])
            except Exception:
                pass
        
        if os.path.exists(b["audio_path"]):
            try:
                os.remove(b["audio_path"])
            except Exception:
                pass

    data["schedules"].pop(target_idx)
    save_data(data)
    return {"message": "일정이 성공적으로 삭제되었습니다."}

@app.post("/api/schedule/play_now")
async def play_now(req: Dict):
    global tts_engine
    if not tts_engine:
        raise HTTPException(status_code=500, detail="TTS 엔진이 아직 초기화되지 않았습니다.")
        
    text = req.get("text", "").strip()
    voice_name = req.get("voice_name", "F1")
    
    if not text:
        raise HTTPException(status_code=400, detail="재생할 텍스트가 비어 있습니다.")

    temp_id = str(uuid.uuid4())
    audio_filename = f"immediate_{temp_id}.wav"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    
    try:
        # TTS 생성
        tts_engine.synthesize_to_file(text, audio_path, voice_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 음성 합성 중 오류가 발생했습니다: {str(e)}")

    # 즉시 재생 신호를 브라우저들에 송출
    audio_url = f"/api/audio/{audio_filename}"
    await broadcast_play_signal(
        audio_url=audio_url,
        text=text,
        schedule_id="manual",
        broadcast_id=temp_id,
        exam_name="즉시 수동 방송",
        broadcast_type="수동 송출"
    )

    # 10초 뒤 임시 재생 파일 자동 정리를 위한 백그라운드 태스크 수행
    # (오디오 송출은 비동기이므로 브라우저가 다 다운받아 재생하도록 30초 뒤 삭제)
    async def cleanup_file():
        await asyncio.sleep(30)
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass

    asyncio.create_task(cleanup_file())

    # 로그 기록
    data = load_data()
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exam_name": "즉시 수동 방송",
        "broadcast_type": "수동 송출",
        "text": text,
        "status": "success"
    }
    data["logs"].insert(0, log_entry)
    save_data(data)

    return {"message": "즉시 방송 송출 신호를 브라우저로 전송했습니다."}

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
    preview_filename = f"preview_{temp_id}.wav"
    preview_path = os.path.join(AUDIO_DIR, preview_filename)
    
    try:
        tts_engine.synthesize_to_file(text, preview_path, voice_name)
        
        def iterfile():
            with open(preview_path, mode="rb") as file_like:
                yield from file_like
            try:
                os.remove(preview_path)
            except Exception:
                pass

        return StreamingResponse(iterfile(), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 음성 합성 중 오류가 발생했습니다: {str(e)}")

# 8. 오디오 파일 다이렉트 서빙 엔드포인트
@app.get("/api/audio/{filename}")
def get_audio_file(filename: str):
    file_path = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="audio/wav")
    raise HTTPException(status_code=404, detail="오디오 파일을 찾을 수 없습니다.")

@app.get("/api/logs")
def get_logs():
    data = load_data()
    return data["logs"]

# 9. 실시간 브라우저 재생 브로드캐스팅 전용 SSE 채널
@app.get("/api/stream")
async def message_stream(request: Request):
    """
    브라우저 클라이언트가 연결하여 대기하는 SSE 스트림입니다.
    """
    queue = asyncio.Queue()
    connected_clients.append(queue)
    logger.info(f"New client connected. Total connected clients: {len(connected_clients)}")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # 1초마다 큐 메시지 검사 (타임아웃 시 킵어라이브 ping 전송)
                    data = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield f"event: play\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            connected_clients.remove(queue)
            logger.info(f"Client disconnected. Total connected clients: {len(connected_clients)}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# 10. 정적 파일 호스팅
static_path = os.path.join(BASE_DIR, "static")
os.makedirs(static_path, exist_ok=True)

@app.get("/")
def read_index():
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "index.html이 존재하지 않습니다."}

app.mount("/static", StaticFiles(directory=static_path), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True) # 호스트를 0.0.0.0으로 열어 외부 접속 완벽 서빙
