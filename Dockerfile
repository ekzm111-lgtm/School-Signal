# 1. Base Image 설정 (FastAPI 및 Python 구동용 경량 리눅스)
FROM python:3.12-slim

# 2. 필수 시스템 패키지 설치
# (오디오 복원을 위한 libsndfile1 및 깃허브 최신 소스 코드 클론을 위한 git 설치)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /code

# 4. 깃허브 원격 저장소로부터 최신 소스코드(static 폴더 포함) 자동 복사
RUN git clone https://github.com/ekzm111-lgtm/School-Signal.git /tmp/signal \
    && cp -r /tmp/signal/* /code/ \
    && rm -rf /tmp/signal

# 5. 의존성 설치
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 6. 오디오 임시 저장 디렉토리 생성 및 권한 설정
RUN mkdir -p /code/audio && chmod 777 /code/audio

# 7. Hugging Face Spaces는 내부적으로 7860 포트를 수신하므로, 7860으로 서버 구동
# (supertonic은 Hugging Face Hub에서 첫 실행 시 모델을 다운받으므로 가상환경 락 방지를 위해 호스트 0.0.0.0 바인딩)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
