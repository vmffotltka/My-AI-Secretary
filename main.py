import sqlite3
import pathlib
import datetime
import os.path
import re
import datetime
from datetime import timedelta
from dateutil.parser import parse
import requests # requests 라이브러리 추가
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# .env 파일에서 환경 변수를 불러옵니다.
load_dotenv()

from fastmcp import FastMCP

# --- Google Calendar API 관련 import ---
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- 설정 ---
# 1. 여기에 발급받은 API 키를 붙여넣으세요!
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/calendar.readonly"]
SCRIPT_DIR = pathlib.Path(__file__).parent
DB_FILE = SCRIPT_DIR / "secretary.db"
# --- 설정 끝 ---

def get_google_creds():
    """구글 API 인증 정보를 가져오는 함수"""
    creds = None
    token_path = SCRIPT_DIR / "token.json"
    creds_path = SCRIPT_DIR / "credentials.json"
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    return creds

def init_db():
    """데이터베이스와 테이블이 없으면 새로 생성합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    # status 열이 추가된 새로운 todos 테이블
    cur.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '미완료'
        )
    """)
    # expenses 테이블은 그대로 유지됩니다.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY, item TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

mcp = FastMCP("my-ai-secretary")


# --- AI 비서의 '도구(Tool)'들 ---
# --- main.py에 아래 내용으로 교체 또는 추가하세요 ---

def init_db():
    """데이터베이스와 테이블이 없으면 새로 생성합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    # status 열이 추가된 새로운 todos 테이블
    cur.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '미완료'
        )
    """)
    # expenses 테이블은 그대로 유지됩니다.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY, item TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

# --- 새로운 통합 도구: 작업 관리 ---

@mcp.tool()
def add_task(content: str) -> str:
    """새로운 작업을 '미완료' 상태로 추가합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("INSERT INTO todos (task) VALUES (?)", (content,))
    con.commit()
    con.close()
    return f"✅ '{content}' 작업을 추가했습니다."

@mcp.tool()
def show_tasks(status_filter: str = "전체") -> str:
    """
    지정된 상태('전체', '미완료', '완료')의 작업 목록을 보여줍니다.
    
    :param status_filter: 보여줄 작업의 상태. 기본값은 '전체'입니다.
    """
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    
    if status_filter in ["미완료", "완료"]:
        cur.execute("SELECT id, task, status FROM todos WHERE status = ? ORDER BY id", (status_filter,))
    else:
        cur.execute("SELECT id, task, status FROM todos ORDER BY id")
        
    tasks = cur.fetchall()
    con.close()
    
    if not tasks:
        return "관리할 작업이 없습니다."
    
    # 상태에 따라 아이콘을 붙여줍니다.
    def get_icon(status):
        return "✅" if status == "완료" else "☑️"

    formatted_list = "\n".join(f"{get_icon(status)} {task_id}. {task}" for task_id, task, status in tasks)
    return f"'{status_filter}' 작업 목록입니다:\n{formatted_list}"

@mcp.tool()
def complete_task(task_id: int) -> str:
    """ID에 해당하는 작업을 '완료' 상태로 변경합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("UPDATE todos SET status = '완료' WHERE id = ?", (task_id,))
    
    if cur.rowcount == 0:
        con.close()
        return f"🤔 ID {task_id}번 작업을 찾을 수 없습니다."
    
    con.commit()
    con.close()
    return f"🎉 {task_id}번 작업을 완료 처리했습니다!"

@mcp.tool()
def delete_task(task_id: int) -> str:
    """ID에 해당하는 작업을 삭제합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("DELETE FROM todos WHERE id = ?", (task_id,))
    
    if cur.rowcount == 0:
        con.close()
        return f"🤔 ID {task_id}번 작업을 찾을 수 없습니다."
        
    con.commit()
    con.close()
    return f"🗑️ {task_id}번 작업을 삭제했습니다."

@mcp.tool()
def get_daily_briefing() -> str:
    """
    오늘의 첫 캘린더 일정, 현재 날씨, 최신 뉴스 헤드라인을 종합하여 브리핑 보고서를 생성합니다.
    """
    briefing_parts = []

    # 1. 구글 캘린더에서 오늘 첫 일정 가져오기
    try:
        creds = get_google_creds()
        service = build("calendar", "v3", credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
        events_result = service.events().list(
            calendarId="primary", timeMin=now, maxResults=1, singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            briefing_parts.append("오늘 예정된 일정이 없습니다.")
        else:
            event = events[0]
            start = event["start"].get("dateTime", event["start"].get("date"))
            start_time = parse(start).strftime('%p %I:%M')
            briefing_parts.append(f"오늘의 첫 일정은 '{event['summary']}'(이)가 {start_time}에 있습니다.")
    except Exception as e:
        briefing_parts.append(f"캘린더 정보를 가져오는 데 실패했습니다: {e}")

    # 2. OpenWeatherMap에서 현재 날씨 가져오기
    try:
        weather_url = f"http://api.openweathermap.org/data/2.5/weather?q=Seoul&appid={OPENWEATHER_API_KEY}&units=metric&lang=kr"
        response = requests.get(weather_url)
        weather_data = response.json()
        description = weather_data['weather'][0]['description']
        temp = weather_data['main']['temp']
        briefing_parts.append(f"현재 서울 날씨는 '{description}'이며, 기온은 {temp}°C입니다.")
    except Exception as e:
        briefing_parts.append("날씨 정보를 가져오는 데 실패했습니다.")

    # 3. NewsAPI에서 최신 뉴스 헤드라인 가져오기
    try:
        # 국가를 'us'로 변경하여 영문 뉴스를 가져옵니다.
        news_url = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWS_API_KEY}"
        response = requests.get(news_url)
        news_data = response.json()
        articles = news_data.get("articles", [])
        
        # --- 번역 코드 시작 ---
        headlines_ko = []
        translator = GoogleTranslator(source='en', target='ko')
        for article in articles[:3]: # 상위 3개만
            translated_title = translator.translate(article['title'])
            headlines_ko.append(f"- {translated_title}")
        # --- 번역 코드 끝 ---

        if headlines_ko:
            briefing_parts.append("주요 IT 뉴스:\n" + "\n".join(headlines_ko))
        else:
            briefing_parts.append("최신 뉴스를 가져올 수 없습니다.")
    except Exception as e:
        briefing_parts.append(f"뉴스 정보를 가져오는 데 실패했습니다: {e}")
        
    # 4. 모든 정보를 합쳐서 최종 보고서 초안을 만듦
    return "\n\n".join(briefing_parts)

@mcp.tool()
def log_expense(item: str, amount: float) -> str:
    """지출 항목과 금액을 데이터베이스에 기록합니다."""
    now = datetime.datetime.now().isoformat()
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("INSERT INTO expenses (item, amount, created_at) VALUES (?, ?, ?)", (item, amount, now))
    con.commit()
    con.close()
    # 숫자에 콤마를 넣어 보기 좋게 표시합니다.
    return f"💸 {amount:,.0f}원 지출('{item}') 내역을 기록했습니다."


@mcp.tool()
def summarize_expenses() -> str:
    """오늘 하루 동안의 총 지출을 요약해서 알려줍니다."""
    # 오늘의 시작 시간을 구합니다.
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    # 오늘 기록된 지출 내역의 합계를 구합니다.
    cur.execute("SELECT SUM(amount) FROM expenses WHERE created_at >= ?", (today_start,))
    total = cur.fetchone()[0] # fetchone()은 (결과,) 형태의 튜플을 반환하므로 [0]으로 값만 추출
    con.close()
    
    if total is None:
        return "오늘 기록된 지출이 없습니다."
    
    return f"오늘의 총 지출은 {total:,.0f}원입니다."

@mcp.tool()
def add_calendar_event(summary: str, time_info: str) -> str:
    """
    설명과 시간 정보를 바탕으로 구글 캘린더에 이벤트를 추가합니다.
    
    :param summary: 이벤트의 제목 (예: "팀 회의")
    :param time_info: 이벤트의 시간 정보 (예: "내일 오후 3시", "오늘 저녁 7시 30분")
    """
    
    def parse_korean_time(time_info: str) -> datetime.datetime:
        """한국어 자연어 시간을 datetime으로 변환"""
        now = datetime.datetime.now()
        
        # 날짜 파싱
        if "내일" in time_info:
            target_date = now + timedelta(days=1)
        elif "모레" in time_info:
            target_date = now + timedelta(days=2)
        elif "오늘" in time_info:
            target_date = now
        else:
            target_date = now
        
        # 시간 추출
        hour_match = re.search(r'(\d+)시', time_info)
        minute_match = re.search(r'(\d+)분', time_info)
        
        if not hour_match:
            raise ValueError("시간을 찾을 수 없습니다")
        
        hour = int(hour_match.group(1))
        minute = int(minute_match.group(1)) if minute_match else 0
        
        # 오전/오후 처리
        if "오후" in time_info and hour != 12:
            hour += 12
        elif "오전" in time_info and hour == 12:
            hour = 0
        elif "저녁" in time_info and hour < 6:
            hour += 12
        elif "밤" in time_info and hour < 12:
            hour += 12
        
        return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    creds = None
    token_path = SCRIPT_DIR / "token.json"
    creds_path = SCRIPT_DIR / "credentials.json"

    # token.json 파일이 있으면, 저장된 인증 정보를 불러옵니다.
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # 인증 정보가 없거나 유효하지 않으면, 새로 로그인합니다.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        # 새로운 인증 정보를 token.json에 저장합니다.
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)
        
        # 한국어 자연어 시간 정보를 datetime 객체로 변환
        start_time = parse_korean_time(time_info)
        
        # 기본 이벤트 기간을 1시간으로 설정 (시간이나 분 정보로 조정 가능)
        duration_hours = 1
        if "시간" in time_info:
            duration_match = re.search(r'(\d+)시간', time_info)
            if duration_match:
                duration_hours = int(duration_match.group(1))
        
        end_time = start_time + datetime.timedelta(hours=duration_hours)

        event = {
            "summary": summary,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "Asia/Seoul"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "Asia/Seoul"},
        }

        event = service.events().insert(calendarId="primary", body=event).execute()
        return f"🗓️ 구글 캘린더에 '{event.get('summary')}' 일정을 추가했습니다. ({start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')})"

    except HttpError as error:
        return f"구글 캘린더 연동 중 오류가 발생했습니다: {error}"
    except ValueError as e:
        return f"시간 정보('{time_info}')를 이해하지 못했어요. '내일 오후 3시'처럼 좀 더 명확하게 말씀해주세요. 오류: {e}"
    except Exception as e:
        return f"예상치 못한 오류가 발생했습니다: {e}"

@mcp.tool()
def get_current_time() -> str:
    """현재 시간을 알려줍니다."""
    now = datetime.datetime.now()
    return f"지금은 {now.strftime('%Y년 %m월 %d일 %H시 %M분')}입니다."

@mcp.tool()
def summarize_youtube_video(video_url: str) -> str:
    """
    주어진 YouTube 영상 URL의 전체 스크립트를 추출하여 텍스트로 반환합니다.
    실제 요약은 이 결과를 받은 Claude가 수행합니다.
    """
    try:
        import re
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # 다양한 YouTube URL 형태에서 비디오 ID 추출
        def extract_video_id(url):
            # 정규표현식을 사용해 다양한 YouTube URL 형태 지원
            patterns = [
                r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|m\.youtube\.com\/watch\?v=)([^&\n?#]+)',
                r'youtube\.com\/shorts\/([^&\n?#]+)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)
            
            raise ValueError("유효하지 않은 YouTube URL입니다.")
        
        video_id = extract_video_id(video_url)
        
        # YouTubeTranscriptApi 인스턴스 생성
        ytt_api = YouTubeTranscriptApi()
        
        try:
            # 먼저 사용 가능한 자막 목록 확인
            transcript_list = ytt_api.list(video_id)
            
            # 사용 가능한 언어들 로깅 (디버깅용)
            available_languages = []
            for transcript in transcript_list:
                available_languages.append({
                    'language': transcript.language,
                    'language_code': transcript.language_code,
                    'is_generated': transcript.is_generated
                })
            print(f"사용 가능한 자막: {available_languages}")
            
        except Exception as e:
            return f"자막 목록을 가져올 수 없습니다: {e}"
        
        # 한국어 우선, 그 다음 영어로 자막 찾기
        transcript = None
        try:
            # 한국어 자막 먼저 시도
            transcript = transcript_list.find_transcript(['ko', 'kr'])
        except:
            try:
                # 영어 자막 시도
                transcript = transcript_list.find_transcript(['en'])
            except:
                try:
                    # 첫 번째 사용 가능한 자막 사용
                    transcript = transcript_list._transcripts[0] if transcript_list._transcripts else None
                except:
                    pass
        
        if transcript is None:
            return f"사용 가능한 자막을 찾을 수 없습니다. 사용 가능한 언어: {[t.language_code for t in transcript_list]}"
        
        # 자막 데이터 가져오기
        try:
            fetched_transcript = transcript.fetch()
            
            # 텍스트 추출 (새 API에서는 .text 속성 사용)
            full_transcript = " ".join([snippet.text.strip() for snippet in fetched_transcript if snippet.text.strip()])
            
            # 너무 긴 텍스트는 자르기 (토큰 제한 고려)
            if len(full_transcript) > 10000:
                full_transcript = full_transcript[:10000] + "... (텍스트가 너무 길어 일부만 표시됩니다)"
            
            # Claude에게 요약을 요청하기 위해 전체 스크립트를 반환
            return f"아래는 영상의 전체 스크립트입니다 (언어: {transcript.language}). 이 내용을 바탕으로 사용자에게 핵심 내용을 3~5문장으로 요약해주세요:\n\n{full_transcript}"
            
        except Exception as e:
            return f"자막 데이터를 가져오는 데 실패했습니다: {e}"

    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"스크립트를 가져오는 데 실패했습니다. 자막이 없는 영상이거나 접근할 수 없는 영상일 수 있습니다. 오류: {type(e).__name__}: {e}"
    
# --- 도구 정의 끝 ---

# --- 서버 실행 ---
if __name__ == "__main__":
    init_db()
    mcp.run(transport='stdio')