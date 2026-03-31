import streamlit as st
import pandas as pd
import re
import sqlite3
from datetime import datetime, timedelta, timezone
import googleapiclient.discovery
import googleapiclient.errors
import google.generativeai as genai

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

# API 초기화
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. 상수 및 데이터 설정] ---
COUNTRIES = {"대한민국": "KR", "미국": "US", "일본": "JP"}
SUB_RANGES = {"전체": (0, 100000000), "1만 ~ 5만": (10000, 50000), "5만 ~ 10만": (50000, 100000), "10만 ~ 50만": (100000, 500000), "50만 이상": (500000, 100000000)}

# 요청하신 정렬 순서 정의
COLUMN_ORDER = [
    '닉네임', '인스타그램 계정', '블로그 계정', '틱톡 계정', '이메일', 
    '제품명', 'DM 발송/개인 컨택', '회신 현황', '원고료', '수령자명', 
    '전화번호', '주소', '택배 발송 요청', '업로드 시 링크', '수치 확인 일자', 
    '조회수', '좋아요', '댓글', '팔로워', 'ER(%)'
]

# --- [3. DB 및 관리 기능] ---
def init_db():
    conn = sqlite3.connect('usage_log.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_usage 
                 (id INTEGER PRIMARY KEY, youtube_count INTEGER, ai_count INTEGER, last_reset TEXT)''')
    c.execute("SELECT count(*) FROM api_usage")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO api_usage (id, youtube_count, ai_count, last_reset) VALUES (1, 0, 0, ?)", 
                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    conn.commit()
    conn.close()

init_db()

def manage_api_quota(yt_add=0, ai_add=0):
    conn = sqlite3.connect('usage_log.db')
    c = conn.cursor()
    c.execute("SELECT youtube_count, ai_count, last_reset FROM api_usage WHERE id=1")
    yt_current, ai_current, last_reset_str = c.fetchone()
    
    # 한국 시간 기준 리셋 로직 (매일 17시)
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    if yt_add > 0 or ai_add > 0:
        c.execute("UPDATE api_usage SET youtube_count = youtube_count + ?, ai_count = ai_count + ? WHERE id=1", (yt_add, ai_add))
        conn.commit()
    conn.close()
    return yt_current, ai_current

# --- [4. 핵심 분석 로직] ---

def get_er_and_metrics(up_id, subs):
    """최근 15개 영상 데이터를 기반으로 ER 및 주요 수치 계산"""
    try:
        manage_api_quota(yt_add=2)
        # 1. 최근 영상 15개 ID 가져오기
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        if not v_ids: return 0, 0, 0, 0
        
        # 2. 영상별 상세 통계 가져오기
        v_res = YOUTUBE.videos().list(part="statistics", id=",".join(v_ids)).execute()
        
        total_views = 0
        total_likes = 0
        total_comments = 0
        count = len(v_res['items'])
        
        for v in v_res['items']:
            stats = v['statistics']
            total_views += int(stats.get('viewCount', 0))
            total_likes += int(stats.get('likeCount', 0))
            total_comments += int(stats.get('commentCount', 0))
            
        avg_views = total_views / count if count > 0 else 0
        # ER(%) 계산: (좋아요 + 댓글) / 조회수 * 100
        er = ((total_likes + total_comments) / total_views * 100) if total_views > 0 else 0
        
        return int(avg_views), total_likes, total_comments, round(er, 2)
    except:
        return 0, 0, 0, 0

def extract_email_ai(desc):
    if not desc or len(desc) < 5: return ""
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
    if emails: return emails[0]
    
    try:
        manage_api_quota(ai_add=1)
        response = model.generate_content(f"텍스트에서 이메일만 추출해. 없으면 공백 반환: {desc[:500]}")
        res = response.text.strip()
        return res if "@" in res else ""
    except: return ""

def get_recent_ad_videos_ai(up_id):
    # (기존 기능 유지) 최근 20개 중 광고 의심 판별
    try:
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=20).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        final_ads = []
        patterns = ["유료 광고", "협찬", "광고", "AD", "Paid", "제작 지원"]
        for v in v_res.get('items', []):
            title = v['snippet']['title']
            desc = v['snippet'].get('description', '')
            if any(p in title for p in patterns) or any(p in desc for p in patterns):
                final_ads.append({"영상 제목": title, "조회수": v['statistics'].get('viewCount',0), "링크": f"https://youtu.be/{v['id']}"})
        return pd.DataFrame(final_ads)
    except: return pd.DataFrame()

# --- [5. UI 레이아웃] ---
st.set_page_config(page_title="Glowup Rizz ER 분석 엔진", layout="wide")

with st.sidebar:
    st.title("⚙️ 관리 및 현황")
    yt_used, ai_used = manage_api_quota()
    st.metric("YouTube API 사용량", f"{yt_used:,}")
    st.metric("AI 분석 호출수", f"{ai_used:,}")
    st.divider()
    st.caption("문의: 010-8900-6756")

st.title("🌐 유튜브 크리에이터 ER 분석 툴")
st.markdown("최근 15개 영상의 데이터를 기반으로 **진성 참여율(ER)**을 분석합니다.")

with st.form("search_form"):
    kws = st.text_input("검색 키워드 (쉼표로 구분)")
    c1, c2, c3 = st.columns(3)
    with c1: country = st.selectbox("국가", list(COUNTRIES.keys()))
    with c2: sub_range = st.selectbox("구독자 범위", list(SUB_RANGES.keys()))
    with c3: limit = st.number_input("검색 샘플 수", 5, 50, 10)
    
    submit = st.form_submit_button("🚀 분석 및 리스트 생성")

if submit and kws:
    keywords = [k.strip() for k in kws.split(",")]
    min_s, max_s = SUB_RANGES[sub_range]
    results = []
    
    prog = st.progress(0)
    total_steps = len(keywords) * limit
    step = 0
    
    for kw in keywords:
        search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=limit, regionCode=COUNTRIES[country]).execute()
        
        for item in search.get('items', []):
            step += 1
            prog.progress(min(step/total_steps, 1.0))
            
            cid = item['snippet']['channelId']
            ch_res = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=cid).execute()
            if not ch_res['items']: continue
            
            ch = ch_res['items'][0]
            subs = int(ch['statistics'].get('subscriberCount', 0))
            if not (min_s <= subs <= max_s): continue
            
            up_id = ch['contentDetails']['relatedPlaylists']['uploads']
            avg_v, t_likes, t_comments, er_val = get_er_and_metrics(up_id, subs)
            email = extract_email_ai(ch['snippet']['description'])
            
            # 요청하신 20개 컬럼 데이터 구성
            row = {
                '닉네임': ch['snippet']['title'],
                '인스타그램 계정': "", # API 자동추출 불가 (수동기입용)
                '블로그 계정': "",
                '틱톡 계정': "",
                '이메일': email,
                '제품명': "",
                'DM 발송/개인 컨택': "",
                '회신 현황': "",
                '원고료': "",
                '수령자명': "",
                '전화번호': "",
                '주소': "",
                '택배 발송 요청': "",
                '업로드 시 링크': "",
                '수치 확인 일자': datetime.now().strftime('%Y-%m-%d'),
                '조회수': avg_v,
                '좋아요': t_likes,
                '댓글': t_comments,
                '팔로워': subs,
                'ER(%)': er_val,
                'upload_id': up_id # 히든 데이터
            }
            results.append(row)
            
    st.session_state.search_df = pd.DataFrame(results)

# --- [6. 결과 출력] ---
if "search_df" in st.session_state:
    df_display = st.session_state.search_df[COLUMN_ORDER]
    
    st.subheader(f"📊 분석 결과 ({len(df_display)}건)")
    
    # 하이라이트: ER 5% 이상은 초록색
    def highlight_er(val):
        color = 'background-color: #d4edda' if val >= 5 else ''
        return color

    st.dataframe(
        df_display.style.applymap(highlight_er, subset=['ER(%)']),
        use_container_width=True,
        hide_index=True
    )
    
    # 엑셀 다운로드 버튼
    csv = df_display.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 결과 리스트 다운로드 (Excel/CSV)", csv, "creator_list.csv", "text/csv")

    st.divider()
    
    # 선택 채널 딥리서치
    st.subheader("🔍 채널별 상세 광고 이력 분석")
    selected_name = st.selectbox("분석할 채널 선택", df_display['닉네임'].tolist())
    if st.button("광고 이력 스캔"):
        target_row = st.session_state.search_df[st.session_state.search_df['닉네임'] == selected_name].iloc[0]
        with st.spinner("최근 영상 분석 중..."):
            ad_df = get_recent_ad_videos_ai(target_row['upload_id'])
            if not ad_df.empty:
                st.warning(f"최근 20개 영상 중 {len(ad_df)}개의 광고 의심 영상이 발견되었습니다.")
                st.table(ad_df)
            else:
                st.success("최근 영상에서 뚜렷한 광고 이력이 발견되지 않았습니다.")
