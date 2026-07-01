// Global State
let voices = [];
let schedules = [];
let activeTimer = null;
let nextBroadcastJob = null;

// DOM Elements
const currentTimeEl = document.getElementById('current-time');
const currentDateEl = document.getElementById('current-date');
const scheduleForm = document.getElementById('schedule-form');
const voiceSelect = document.getElementById('voice-select');
const manualVoiceSelect = document.getElementById('manual-voice-select');
const toggleTemplatesBtn = document.getElementById('toggle-templates-btn');
const templatesContent = document.getElementById('templates-content');
const scheduleList = document.getElementById('schedule-list');
const logsTbody = document.getElementById('logs-tbody');
const toastEl = document.getElementById('toast');
const toastMessageEl = document.getElementById('toast-message');

// Countdown Elements
const countdownTimerEl = document.getElementById('countdown-timer');
const countdownProgressEl = document.getElementById('countdown-progress');
const nextExamNameEl = document.getElementById('next-exam-name');
const nextBroadcastTimeEl = document.getElementById('next-broadcast-time');
const nextBroadcastTextEl = document.getElementById('next-broadcast-text');

// Init
document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    
    // Load Voice options
    fetchVoices();
    
    // Load Schedules & Logs
    refreshAll();
    
    // Periodic refresh every 10 seconds to keep UI sync
    setInterval(refreshAll, 10000);

    // Event Listeners
    scheduleForm.addEventListener('submit', handleScheduleSubmit);
    toggleTemplatesBtn.addEventListener('click', toggleTemplatesAccordion);
    
    // Quick time select listener
    const quickTimeSelect = document.getElementById('quick-time-select');
    quickTimeSelect.addEventListener('change', (e) => {
        const selectedOpt = e.target.selectedOptions[0];
        if (!selectedOpt || !selectedOpt.value) return;
        
        const name = selectedOpt.getAttribute('data-name');
        const time = selectedOpt.value;
        
        const examNameInput = document.getElementById('exam-name');
        const endTimeInput = document.getElementById('end-time');
        
        const currentVal = examNameInput.value.trim();
        // 앞부분의 'N교시' 패턴이 있으면 제거하고 뒤의 과목명만 추출
        const cleanNameMatch = currentVal.match(/^[1-7]교시\s*(.*)$/);
        const pureSubject = cleanNameMatch ? cleanNameMatch[1] : currentVal;
        
        if (pureSubject) {
            examNameInput.value = `${name} ${pureSubject}`;
        } else {
            examNameInput.value = `${name} `;
        }
        
        endTimeInput.value = time;
        examNameInput.focus();
    });
    
    document.getElementById('refresh-schedule-btn').addEventListener('click', loadSchedules);
    document.getElementById('refresh-logs-btn').addEventListener('click', loadLogs);
    
    document.getElementById('preview-btn').addEventListener('click', handlePreview);
    document.getElementById('play-now-btn').addEventListener('click', handlePlayNow);

    // 스피커 송출 제어 토글 및 SSE 연동
    const toggle = document.getElementById('enable-broadcast-toggle');
    const hostname = window.location.hostname;
    
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        toggle.checked = true;
    } else {
        toggle.checked = false;
    }
    
    initSSE();
    
    toggle.addEventListener('change', () => {
        updateSpeakerStatus();
        if (toggle.checked) {
            showToast('방송 송출 수신이 활성화되었습니다. 브라우저 보안 정책상 화면의 아무 곳이나 한 번 클릭해 주세요!', 'info');
        } else {
            showToast('이 화면에서의 방송 송출 수신을 비활성화했습니다.', 'info');
        }
    });

    document.body.addEventListener('click', () => {
        if (toggle.checked && !window.audioUnlocked) {
            window.audioUnlocked = true;
            try {
                // Web Audio API를 활용해 실제 소리를 단기간 냄으로써 크롬의 오토플레이 제한을 강제로 완전히 풉니다.
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) {
                    const ctx = new AudioContext();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    gain.gain.setValueAtTime(0.001, ctx.currentTime); // 귀에 안 들릴 정도의 초미세음량
                    osc.start(0);
                    osc.stop(ctx.currentTime + 0.05);
                    ctx.resume();
                    console.log("AudioContext unlocked via Web Audio API");
                }
            } catch (err) {
                console.error("Audio unlock error:", err);
            }
            showToast('소리 재생 권한이 활성화되었습니다.', 'success');
        }
    }, { once: true });
});

// Toast System
function showToast(message, type = 'info') {
    toastEl.className = `toast-notification ${type}`;
    toastMessageEl.textContent = message;
    
    // Icons based on type
    const iconEl = toastEl.querySelector('.toast-icon');
    iconEl.className = 'toast-icon fa-solid';
    if (type === 'success') iconEl.classList.add('fa-circle-check');
    else if (type === 'error') iconEl.classList.add('fa-triangle-exclamation');
    else iconEl.classList.add('fa-circle-info');
    
    toastEl.classList.add('show');
    
    setTimeout(() => {
        toastEl.classList.remove('show');
    }, 4000);
}

// Update Clock
function updateClock() {
    const now = new Date();
    
    // Time format: HH:MM:SS
    const hrs = String(now.getHours()).padStart(2, '0');
    const mins = String(now.getMinutes()).padStart(2, '0');
    const secs = String(now.getSeconds()).padStart(2, '0');
    currentTimeEl.textContent = `${hrs}:${mins}:${secs}`;
    
    // Date format: YYYY년 MM월 DD일 요일
    const years = now.getFullYear();
    const months = String(now.getMonth() + 1).padStart(2, '0');
    const dates = String(now.getDate()).padStart(2, '0');
    
    const weekdays = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
    const day = weekdays[now.getDay()];
    currentDateEl.textContent = `${years}년 ${months}월 ${dates}일 ${day}`;
    
    // Update countdown timer
    updateCountdown(now);
}

// Fetch Voices
async function fetchVoices() {
    try {
        const response = await fetch('/api/voices');
        if (!response.ok) throw new Error('Failed to load voices');
        voices = await response.json();
        
        // Populate select elements
        [voiceSelect, manualVoiceSelect].forEach(select => {
            select.innerHTML = '';
            voices.forEach(voice => {
                const opt = document.createElement('option');
                opt.value = voice.id;
                opt.textContent = voice.name;
                select.appendChild(opt);
            });
        });
    } catch (e) {
        logger.error('Error fetching voices:', e);
        showToast('목소리 목록을 불러오지 못했습니다.', 'error');
    }
}

// Refresh All
function refreshAll() {
    loadSchedules();
    loadLogs();
}

// Load Schedules
async function loadSchedules() {
    try {
        const response = await fetch('/api/schedule');
        if (!response.ok) throw new Error('Failed to load schedules');
        schedules = await response.json();
        renderSchedules();
        findNextBroadcast();
    } catch (e) {
        console.error('Error loading schedules:', e);
    }
}

// Load Logs
async function loadLogs() {
    try {
        const response = await fetch('/api/logs');
        if (!response.ok) throw new Error('Failed to load logs');
        const logs = await response.json();
        renderLogs(logs);
    } catch (e) {
        console.error('Error loading logs:', e);
    }
}

// Render Schedules
function renderSchedules() {
    if (schedules.length === 0) {
        scheduleList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-calendar-xmark empty-icon"></i>
                <p>등록된 시험 방송 일정이 없습니다.</p>
                <span>위 폼을 작성해 첫 시험 일정을 등록해 보세요.</span>
            </div>
        `;
        return;
    }
    
    // Sort schedules by end_time
    schedules.sort((a, b) => new Date(a.end_time) - new Date(b.end_time));
    
    scheduleList.innerHTML = '';
    schedules.forEach(sched => {
        const item = document.createElement('div');
        item.className = 'schedule-item';
        
        // Format end_time for presentation
        const endTimeObj = new Date(sched.end_time);
        const formattedEndTime = `${String(endTimeObj.getHours()).padStart(2, '0')}:${String(endTimeObj.getMinutes()).padStart(2, '0')}`;
        
        // Sub broadcasts list
        let broadcastRows = '';
        sched.broadcasts.sort((a, b) => new Date(a.trigger_time) - new Date(b.trigger_time));
        
        sched.broadcasts.forEach(b => {
            const trigTime = new Date(b.trigger_time);
            const timeStr = `${String(trigTime.getHours()).padStart(2, '0')}:${String(trigTime.getMinutes()).padStart(2, '0')}:${String(trigTime.getSeconds()).padStart(2, '0')}`;
            
            let statusBadge = '';
            if (b.status === 'pending') statusBadge = '<span class="badge badge-pending">대기 중</span>';
            else if (b.status === 'playing') statusBadge = '<span class="badge badge-playing">송출 중</span>';
            else if (b.status === 'completed') statusBadge = '<span class="badge badge-completed">완료</span>';
            else if (b.status === 'failed') statusBadge = '<span class="badge badge-failed">오류</span>';
            else if (b.status === 'expired') statusBadge = '<span class="badge badge-expired">만료됨</span>';
            
            const offsetLabel = b.offset_minutes === 0 ? '종료 정시' : `${b.offset_minutes}분 전`;
            
            broadcastRows += `
                <div class="broadcast-subitem">
                    <span class="broadcast-subitem-time"><i class="fa-regular fa-clock"></i> ${timeStr}</span>
                    <span class="broadcast-subitem-label">${offsetLabel} 안내</span>
                    ${statusBadge}
                </div>
            `;
        });
        
        const voiceText = voices.find(v => v.id === sched.voice_name)?.name || sched.voice_name;

        item.innerHTML = `
            <div class="schedule-item-header">
                <div>
                    <h3 class="schedule-item-title">${sched.exam_name}</h3>
                    <div class="schedule-item-meta">
                        <span><i class="fa-solid fa-flag-check"></i> 종료 시각: ${formattedEndTime}</span>
                        <span><i class="fa-solid fa-user-tie"></i> 목소리: ${voiceText}</span>
                    </div>
                </div>
                <button class="btn-danger-sm delete-schedule-btn" data-id="${sched.id}">
                    <i class="fa-solid fa-trash-can"></i> 삭제
                </button>
            </div>
            <div class="broadcast-sublist">
                ${broadcastRows}
            </div>
        `;
        
        // Delete button listener
        item.querySelector('.delete-schedule-btn').addEventListener('click', async (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            if (confirm('이 시험 일정을 취소하고 삭제하시겠습니까? (이미 생성된 예약 방송들도 모두 취소됩니다.)')) {
                await deleteSchedule(id);
            }
        });
        
        scheduleList.appendChild(item);
    });
}

// Render Logs
function renderLogs(logs) {
    if (!logs || logs.length === 0) {
        logsTbody.innerHTML = `
            <tr>
                <td colspan="5" class="empty-row">송출 기록이 존재하지 않습니다.</td>
            </tr>
        `;
        return;
    }
    
    logsTbody.innerHTML = '';
    logs.slice(0, 50).forEach(log => { // Max 50 logs shown
        const row = document.createElement('tr');
        
        const statusClass = log.status === 'success' ? 'success' : 'failed';
        const statusText = log.status === 'success' ? '성공' : '실패';
        
        row.innerHTML = `
            <td>${log.timestamp}</td>
            <td style="font-weight:600;">${log.exam_name}</td>
            <td>${log.broadcast_type}</td>
            <td title="${log.text}" style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${log.text}</td>
            <td><span class="log-status ${statusClass}">${statusText}</span></td>
        `;
        logsTbody.appendChild(row);
    });
}

// Delete Schedule
async function deleteSchedule(id) {
    try {
        const response = await fetch(`/api/schedule/${id}`, { method: 'DELETE' });
        const result = await response.json();
        if (response.ok) {
            showToast(result.message, 'success');
            refreshAll();
        } else {
            showToast(result.detail || '삭제에 실패했습니다.', 'error');
        }
    } catch (e) {
        console.error('Delete error:', e);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

// Handle Form Submit
async function handleScheduleSubmit(e) {
    e.preventDefault();
    
    const examName = document.getElementById('exam-name').value;
    const endTime = document.getElementById('end-time').value;
    const voiceName = voiceSelect.value;
    
    // Gather checkboxes
    const offsetCheckboxes = document.querySelectorAll('input[name="offsets"]:checked');
    const offsets = Array.from(offsetCheckboxes).map(cb => parseInt(cb.value));
    
    if (offsets.length === 0) {
        showToast('최소 하나의 송출 시점을 선택해야 합니다.', 'error');
        return;
    }
    
    // Gather custom templates
    const customTemplates = {};
    const possibleOffsets = [10, 5, 1, 0];
    possibleOffsets.forEach(offset => {
        const val = document.getElementById(`template-${offset}`).value;
        if (val.trim()) {
            customTemplates[String(offset)] = val.trim();
        }
    });
    
    const payload = {
        exam_name: examName,
        end_time: endTime,
        offsets: offsets,
        voice_name: voiceName,
        custom_templates: Object.keys(customTemplates).length > 0 ? customTemplates : null
    };
    
    // Disable submit button
    const submitBtn = document.getElementById('submit-schedule-btn');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 생성 및 음성 합성 중...';
    
    try {
        const response = await fetch('/api/schedule', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        if (response.ok) {
            showToast(`${examName} 일정이 정상 등록되었습니다.`, 'success');
            scheduleForm.reset();
            // Default select checkboxes again
            document.querySelectorAll('input[name="offsets"]').forEach(cb => cb.checked = true);
            // Close accordion if open
            toggleTemplatesBtn.classList.remove('active');
            templatesContent.style.maxHeight = null;
            templatesContent.style.padding = null;
            templatesContent.style.borderTop = null;
            
            refreshAll();
        } else {
            showToast(result.detail || '등록 실패', 'error');
        }
    } catch (e) {
        console.error('Submit error:', e);
        showToast('일정 등록 과정에서 오류가 발생했습니다.', 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

// Find Next Broadcast Job
function findNextBroadcast() {
    const now = new Date();
    let nextJob = null;
    let minDiff = Infinity;
    let associatedExam = '';
    
    schedules.forEach(sched => {
        sched.broadcasts.forEach(b => {
            if (b.status === 'pending') {
                const trigTime = new Date(b.trigger_time);
                const diff = trigTime - now;
                if (diff > 0 && diff < minDiff) {
                    minDiff = diff;
                    nextJob = b;
                    associatedExam = sched.exam_name;
                }
            }
        });
    });
    
    nextBroadcastJob = nextJob ? { ...nextJob, exam_name: associatedExam } : null;
    
    // Update labels in real-time card
    if (nextBroadcastJob) {
        nextExamNameEl.textContent = nextBroadcastJob.exam_name;
        const trig = new Date(nextBroadcastJob.trigger_time);
        nextBroadcastTimeEl.textContent = `${String(trig.getHours()).padStart(2, '0')}:${String(trig.getMinutes()).padStart(2, '0')}:${String(trig.getSeconds()).padStart(2, '0')} (${nextBroadcastJob.offset_minutes === 0 ? '종료 정시' : nextBroadcastJob.offset_minutes + '분 전'})`;
        nextBroadcastTextEl.textContent = nextBroadcastJob.text;
        nextBroadcastTextEl.title = nextBroadcastJob.text;
    } else {
        nextExamNameEl.textContent = '-';
        nextBroadcastTimeEl.textContent = '-';
        nextBroadcastTextEl.textContent = '대기 중인 안내 방송이 없습니다.';
        countdownTimerEl.textContent = '--:--:--';
        countdownProgressEl.style.strokeDashoffset = '0';
    }
}

// Update countdown circle & time text
function updateCountdown(nowDate) {
    if (!nextBroadcastJob) return;
    
    const triggerTime = new Date(nextBroadcastJob.trigger_time);
    const diffMs = triggerTime - nowDate;
    
    if (diffMs <= 0) {
        // Time to trigger
        countdownTimerEl.textContent = '00:00:00';
        countdownProgressEl.style.strokeDashoffset = '283';
        nextBroadcastJob = null; // Reset
        // Trigger immediate reload of state
        setTimeout(refreshAll, 1500);
        return;
    }
    
    // Calc HH:MM:SS
    const totalSecs = Math.floor(diffMs / 1000);
    const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
    const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
    const secs = String(totalSecs % 60).padStart(2, '0');
    
    countdownTimerEl.textContent = `${hrs}:${mins}:${secs}`;
    
    // SVG Circular progress bar update
    // Stroke dasharray = 283 (which is 2 * pi * r = 2 * 3.14159 * 45 ≈ 283)
    // We assume max gauge length is 1 hour (3600s) or less, dynamically scaling it.
    // If remaining time is > 1 hour, we keep gauge full.
    const maxPeriod = 3600; // 1 hour reference
    const percentage = Math.min(totalSecs / maxPeriod, 1);
    const offset = 283 - (percentage * 283);
    countdownProgressEl.style.strokeDashoffset = offset;
}

// Toggle accordion
function toggleTemplatesAccordion() {
    toggleTemplatesBtn.classList.toggle('active');
    
    if (toggleTemplatesBtn.classList.contains('active')) {
        templatesContent.style.maxHeight = '500px';
        templatesContent.style.padding = '16px';
        templatesContent.style.borderTop = '1px solid rgba(255, 255, 255, 0.05)';
    } else {
        templatesContent.style.maxHeight = null;
        templatesContent.style.padding = null;
        templatesContent.style.borderTop = null;
    }
}

// Handle Manual Play Preview
async function handlePreview() {
    const text = document.getElementById('manual-text').value.trim();
    const voiceName = manualVoiceSelect.value;
    
    if (!text) {
        showToast('미리듣기할 텍스트를 입력해 주세요.', 'error');
        return;
    }
    
    const previewBtn = document.getElementById('preview-btn');
    const originalHTML = previewBtn.innerHTML;
    previewBtn.disabled = true;
    previewBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 합성 중...';
    
    try {
        const response = await fetch('/api/tts/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice_name: voiceName })
        });
        
        if (!response.ok) throw new Error('Preview failed');
        
        const blob = await response.blob();
        const audioUrl = URL.createObjectURL(blob);
        
        const audioEl = document.getElementById('preview-audio');
        audioEl.src = audioUrl;
        audioEl.play();
        
        showToast('TTS 미리듣기 음성을 재생합니다.', 'success');
    } catch (e) {
        console.error('Preview error:', e);
        showToast('음성 합성 미리듣기에 실패했습니다.', 'error');
    } finally {
        previewBtn.disabled = false;
        previewBtn.innerHTML = originalHTML;
    }
}

// Handle Manual Play Now (Instant Broadcast)
async function handlePlayNow() {
    const text = document.getElementById('manual-text').value.trim();
    const voiceName = manualVoiceSelect.value;
    
    if (!text) {
        showToast('송출할 텍스트를 입력해 주세요.', 'error');
        return;
    }
    
    if (!confirm('작성하신 내용을 즉시 로컬 스피커로 송출하시겠습니까? (이 방송은 백그라운드 스레드에서 곧바로 실행됩니다.)')) {
        return;
    }
    
    const playBtn = document.getElementById('play-now-btn');
    const originalHTML = playBtn.innerHTML;
    playBtn.disabled = true;
    playBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 전송 중...';
    
    try {
        const response = await fetch('/api/schedule/play_now', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice_name: voiceName })
        });
        
        const result = await response.json();
        if (response.ok) {
            showToast(result.message, 'success');
            document.getElementById('manual-text').value = '';
            setTimeout(refreshAll, 2000);
        } else {
            showToast(result.detail || '송출 실패', 'error');
        }
    } catch (e) {
        console.error('Play now error:', e);
        showToast('즉시 송출 처리 중 서버 오류가 발생했습니다.', 'error');
    } finally {
        playBtn.disabled = false;
        playBtn.innerHTML = originalHTML;
    }
}

// ==========================================
// 웹 브라우저 실시간 방송 수신 및 재생 시스템 (SSE)
// ==========================================
let eventSource = null;

function initSSE() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource('/api/stream');
    
    eventSource.onopen = () => {
        console.log("SSE connected.");
        updateSpeakerStatus();
    };
    
    eventSource.onerror = (e) => {
        console.error("SSE error, reconnecting...", e);
        const statusTitle = document.getElementById('speaker-status-title');
        statusTitle.innerHTML = '<i class="fa-solid fa-volume-xmark status-icon"></i> 방송 송출 대기 오프라인';
        statusTitle.className = 'status-disconnected';
    };
    
    eventSource.addEventListener('play', (event) => {
        const data = JSON.parse(event.data);
        console.log("Received play signal:", data);
        
        const toggle = document.getElementById('enable-broadcast-toggle');
        if (toggle.checked) {
            playAudioFromSignal(data.audio_url, data.text);
            setTimeout(refreshAll, 1000);
        } else {
            console.log("Play signal ignored: Speaker toggle is OFF.");
        }
    });
}

function updateSpeakerStatus() {
    const toggle = document.getElementById('enable-broadcast-toggle');
    const statusTitle = document.getElementById('speaker-status-title');
    
    if (toggle.checked) {
        if (eventSource && eventSource.readyState === EventSource.OPEN) {
            statusTitle.innerHTML = '<i class="fa-solid fa-volume-high status-icon"></i> 방송 송출 수신 대기 중 (온라인)';
            statusTitle.className = 'status-connected';
        } else {
            statusTitle.innerHTML = '<i class="fa-solid fa-spinner fa-spin status-icon"></i> 송출 대기 중 연결 시도...';
            statusTitle.className = 'status-disconnected';
        }
    } else {
        statusTitle.innerHTML = '<i class="fa-solid fa-volume-xmark status-icon"></i> 방송 송출 비활성화됨';
        statusTitle.className = 'status-disconnected';
    }
}

function playAudioFromSignal(audioUrl, text) {
    const audio = new Audio(audioUrl);
    audio.play().then(() => {
        showToast(`안내 방송 송출 시작: ${text.substring(0, 20)}...`, 'success');
    }).catch(err => {
        console.error("Browser audio play blocked:", err);
        showToast('브라우저 오디오 재생이 차단되었습니다. 화면을 클릭해 활성화해 주세요!', 'error');
    });
}
