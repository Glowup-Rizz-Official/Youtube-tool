import streamlit as st
import pandas as pd
import re
import time
from datetime import datetime, timedelta
import googleapiclient.discovery
import google.generativeai as genai
import streamlit.components.v1 as components

# --- [0. 세션 상태 및 할당량 추적기 초기화] ---
if "youtube_points" not in st.session_state:
    st.session_state.youtube_points = 0
if "ai_calls" not in st.session_state:
    st.session_state.ai_calls = 0

def track_points(amount, is_ai=False):
    if is_ai:
        st.session_state.ai_calls += 1
    else:
        st.session_state.youtube_points += amount

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. UI 설정 및 3D 로고] ---
st.set_page_config(page_title="Glowup Rizz - 크리에이터 분석 엔진", layout="wide")

# 사이드바 설정 (할당량 추적기 포함)
with st.sidebar:
    # Spline 3D 로고
    spline_url = "https://prod.spline.design/https://my.spline.design/spline3dstarterfile-wRU0zWxiYWRpq8uEMf2xSrlh//scene.splinecode"
    components.html(
        f"""
        <script type="module" src="https://unpkg.com/@splinetool/viewer@1.0.55/build/spline-viewer.js"></script>
        <spline-viewer url="{spline_url}"></spline-viewer>
        """,
        height=200,
    )
    
    st.markdown("---")
    st.subheader("📊 실시간 API 할당량")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("YouTube API", f"{st.session_state.youtube_points} pts")
    with col2:
        st.metric("AI Calls", f"{st.session_state.ai_calls}회")
    st.caption("※ YouTube 일일 한도: 500,000 pts")
    st.info("🚀 **Glowup Rizz v5.0**\n1년 치 광고 히스토리 분석 모드")

# 메인 타이틀 및 문의처 (유지)
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [3. 로직 함수들] ---

# --- [하이브리드 이메일 추출 함수] ---
def extract_email_hybrid(desc):
    if not desc or len(desc.strip()) < 5: 
        return "직접 확인 필요"

    # 1단계: 정규표현식(Regex)으로 표준 이메일 패턴 추출 (비용 0원, 속도 무한)
    email_reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
    if email_reg:
        return email_reg[0] # 표준 패턴 발견 시 즉시 반환

    # 2단계: 정규표현식이 실패했을 때만 AI 등판 (AX 정밀 분석)
    # 예: "rizz 골뱅이 네이버" 또는 "문의는 인스타그램 dm이나 메일(rizz at gmail)" 등
    prompt = f"""
    다음 유튜브 채널 설명란에서 비즈니스 연락처(이메일)를 찾아줘. 
    이메일 형식이 숨겨져 있을 수 있어(예: [at], 골뱅이 등).
    찾을 수 없다면 오직 'None'이라고만 답해.
    
    내용: {desc}
    """
    try:
        time.sleep(0.5)
        track_points(1, is_ai=True) # AI를 쓸 때만 카운트
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res or "." in res: # AI가 찾아낸 경우
            return res
        return "직접 확인 필요"
    except:
        return "데이터 확인 필요"

def check_performance(up_id, subs):
    if subs == 0: return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        track_points(1)
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        track_points(1)
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        return (eff >= 0.1), avg_v, eff # 기본 효율 10% 기준
    except: return False, 0, 0

# 1년 치 영상 전수 조사 + 하이브리드 필터링
def get_year_ad_history(up_id):
    one_year_ago = (datetime.utcnow() - timedelta(days=365)).isoformat() + "Z"
    all_ads = []
    next_page_token = None
    official_patterns = ["유료 광고 포함", "Paid promotion", "제작 지원", "협찬", "#광고", "AD"]

    try:
        with st.spinner("최근 1년 치 영상을 전수 분석 중입니다..."):
            while True:
                req = YOUTUBE.playlistItems().list(
                    part="snippet,contentDetails", 
                    playlistId=up_id, 
                    maxResults=50, 
                    pageToken=next_page_token
                ).execute()
                track_points(1)
                
                v_ids = []
                for item in req.get('items', []):
                    pub_at = item['snippet']['publishedAt']
                    if pub_at < one_year_ago:
                        next_page_token = None # 1년 넘어가면 중단
                        break
                    v_ids.append(item['contentDetails']['videoId'])
                
                if v_ids:
                    v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
                    track_points(1)
                    
                    for v in v_res.get('items', []):
                        title = v['snippet']['title']
                        desc = v['snippet'].get('description', '')
                        # 1단계: 하이브리드 공식 표기 검사
                        is_ad = any(p in title or p in desc[:300] for p in official_patterns)
                        
                        if is_ad:
                            all_ads.append({
                                "영상 제목": title,
                                "업로드 일자": datetime.strptime(v['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d'),
                                "조회수": int(v['statistics'].get('viewCount', 0)),
                                "영상 링크": f"https://youtu.be/{v['id']}"
                            })
                
                next_page_token = req.get('nextPageToken')
                if not next_page_token: break
            
        return pd.DataFrame(all_ads)
    except: return pd.DataFrame()

# --- [4. 실행 프로세스] ---
with st.form("search_form"):
    keywords_input = st.text_input("🔎 검색 키워드 (쉼표 구분)", placeholder="먹방, 일상 브이로그")
    submit_button = st.form_submit_button("🚀 크리에이터 검색 시작")

if submit_button:
    if not keywords_input:
        st.warning("검색어를 입력해주세요.")
    else:
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        prog = st.progress(0)
        curr = 0
        total = len(kws) * 20

        with st.status("🔍 분석 중...", expanded=True) as status:
            for kw in kws:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=20, regionCode="KR").execute()
                track_points(100) # 검색은 100포인트
                
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    ch_id = item['snippet']['channelId']
                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=ch_id).execute()['items'][0]
                        track_points(1)
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        if is_ok:
                            final_list.append({
                                "채널명": ch['snippet']['title'],
                                "구독자": subs,
                                "평균조회수": round(avg_v),
                                "효율": f"{eff*100:.1f}%",
                                "이메일": extract_email_ai(ch['snippet']['description']),
                                "URL": f"https://youtube.com/channel/{ch_id}",
                                "프로필": ch['snippet']['thumbnails']['default']['url'],
                                "upload_id": up_id
                            })
                    except: continue
            status.update(label="✅ 분석 완료!", state="complete")
        st.session_state.search_results = pd.DataFrame(final_list)

# 결과 출력 및 1년 치 딥리서치
if "search_results" in st.session_state and not st.session_state.search_results.empty:
    st.subheader("📊 검색 결과")
    event = st.dataframe(
        st.session_state.search_results,
        column_config={"프로필": st.column_config.ImageColumn("프로필"), "URL": st.column_config.LinkColumn("링크", display_text="바로가기"), "upload_id": None},
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        st.markdown("---")
        st.subheader(f"📅 '{ch_info['채널명']}' 최근 1년 광고 히스토리")
        
        ad_df = get_year_ad_history(ch_info['upload_id'])
        if not ad_df.empty:
            st.success(f"🎯 지난 1년간 총 {len(ad_df)}개의 광고/협업 영상이 발견되었습니다.")
            st.dataframe(
                ad_df,
                column_config={"영상 링크": st.column_config.LinkColumn("영상 보기", display_text="바로가기"), "조회수": st.column_config.NumberColumn(format="%d회")},
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("최근 1년 이내에 공식적으로 표기된 광고 영상이 없습니다.")
