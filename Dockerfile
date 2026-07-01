FROM python:3.12-slim

# ONNX Runtime 및 OpenMP 스레드 폭발 방지 (CPU 컨텐션 해결용 성능 극대화 설정)
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV VECLIB_MAXIMUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1

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
# (개행문자 및 인코딩으로 인한 따옴표 에러 방지를 위해 쉘 형식으로 실행)
CMD uvicorn app:app --host 0.0.0.0 --port 7860
