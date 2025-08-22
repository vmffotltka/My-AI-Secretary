import sqlite3
# pathlib 라이브러리를 추가로 불러옵니다.
import pathlib
from fastmcp import FastMCP
import datetime

# --- DB 설정 ---
# 현재 파일(main.py)이 있는 폴더의 절대 경로를 찾습니다.
SCRIPT_DIR = pathlib.Path(__file__).parent
# 그 폴더 안에 'secretary.db' 파일을 생성하도록 경로를 지정합니다.
DB_FILE = SCRIPT_DIR / "secretary.db"

def init_db():
    """데이터베이스와 테이블이 없으면 새로 생성합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()
# --- DB 설정 끝 ---


# FastMCP 서버를 준비합니다.
mcp = FastMCP("my-ai-secretary")


# --- AI 비서의 '도구(Tool)'들 ---

@mcp.tool()
def get_current_time() -> str:
    """현재 시간을 알려줍니다."""
    now = datetime.datetime.now()
    return f"지금은 {now.strftime('%Y년 %m월 %d일 %H시 %M분')}입니다."

@mcp.tool()
def add_todo(item: str) -> str:
    """할 일 목록에 새로운 항목을 추가합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("INSERT INTO todos (task) VALUES (?)", (item,))
    con.commit()
    con.close()
    return f"✅ '{item}' 항목을 할 일 목록에 추가했습니다."

@mcp.tool()
def show_todos() -> str:
    """현재 저장된 모든 할 일 목록을 보여줍니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("SELECT task FROM todos")
    items = [row[0] for row in cur.fetchall()]
    con.close()
    
    if not items:
        return "현재 할 일 목록이 비어있습니다."
    
    formatted_list = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    return f"현재 할 일 목록입니다:\n{formatted_list}"

@mcp.tool()
def remove_todo(item: str) -> str:
    """할 일 목록에서 특정 항목을 삭제합니다."""
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("DELETE FROM todos WHERE task = ?", (item,))
    changes = con.total_changes
    con.commit()
    con.close()
    
    if changes > 0:
        return f"🗑️ '{item}' 항목을 할 일 목록에서 삭제했습니다."
    else:
        return f"🤔 '{item}' 항목을 찾을 수 없습니다."

# --- 도구 정의 끝 ---


# 서버를 직접 실행(STDIO) 방식으로 실행합니다.
if __name__ == "__main__":
    init_db()
    mcp.run(transport='stdio')