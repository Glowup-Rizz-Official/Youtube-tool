import streamlit as st
import pandas as pd
import re
import time
import os
import json
from datetime import datetime, timedelta
import googleapiclient.discovery
import google.generativeai as genai

# --- [0. 팀 공용 할당량 관리 시스템] ---
QUOTA_FILE = "quota.json"

def load_global_stats():
    if not os.path.exists(QUOTA_FILE):
        # 초기 데이터: AI 누적량과 마지막 리셋 시간 기록
        return {"yt_total": 0, "ai_total": 0, "last_reset": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(QUOTA_FILE, "r") as f:
        return json.load(f)

def save_global_stats(stats):
    with open(QUOTA_FILE, "w") as f:
        json.dump(stats, f)

def check_and_reset_quota():
    stats = load_global_stats()
    now = datetime.now()
    last_reset = datetime.strptime(stats["last_reset"], "%Y-%m-%d %H:%M:%S")
    
    # 오늘 오후 5시 기준점
    reset_time_today = now.replace(hour=17, minute=0, second=0, microsecond=0)
    
    # 오후 5시가 넘었으면서 마지막 리셋이 어제 혹은 오늘 17시 이전일 때
    if now >= reset_time_today and last_reset < reset_time_today:
        stats["yt_total"] = 0
        stats["last_reset"] = now.strftime("%Y-%m-%d %H:%M:%S")
        save_global_stats(stats)
    return stats

def track_points_global(amount, is_ai=False):
    stats = load_global_stats()
    if is_ai:
        stats["ai_total"] += 1
    else:
        stats["yt_total"] += amount
    save_global_stats(stats)

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

# --- [2. 데이터 설정] ---
COUNTRIES = {"대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"}
SUB_RANGES = {"전체": (0, 100000000), "1만 미만": (0, 10000), "1만 ~ 5만": (10000, 50000), "5만 ~ 10만": (50000, 100000), "10만 ~ 50만": (100000, 500000), "50만 ~ 100만": (500000, 1000000), "100만 이상": (1000000, 100000000)}

# --- [3. UI 설정 및 사이드바] ---
st.set_page_config(page_title="Glowup Rizz - 팀 공용 분석기", layout="wide")
global_stats = check_and_reset_quota()

# --- [사이드바 내 관리자 전용 영역] ---
with st.sidebar:
    st.markdown("---")
    st.subheader("🛠️ 관리자 설정")
    
    # 1. 암호 입력창 (비밀번호 형식)
    admin_pw = st.text_input("관리자 암호를 입력하세요", type="password", placeholder="Password info")
    
    # 2. 암호가 일치할 때만 리셋 버튼 노출 (예: rizz123)
    if admin_pw == "rizz123": # 혜란님만의 암호로 수정하세요!
        st.success("✅ 관리자 인증 성공")
        if st.button("🔄 AI 호출수 초기화 (결제일용)"):
            global_stats["ai_total"] = 0
            save_global_stats(global_stats)
            st.toast("AI 호출수가 0으로 초기화되었습니다.")
            st.rerun()
    elif admin_pw != "":
        st.error("❌ 암호가 틀렸습니다.")

# [유지] 제목 및 문의처
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [4. 메인 검색 폼 (모든 필터 유지)] ---
with st.form("search_form"):
    st.markdown("📥 **기존 리스트 제외하기 (파일 업로드)**")
    exclude_file = st.file_uploader("이미 확보한 채널 리스트(엑셀/CSV) 업로드", type=['xlsx', 'csv'])
    st.markdown("---")
    
    r1_c1, r1_c2, r1_c3 = st.columns([3, 1, 1])
    with r1_c1:
        keywords_input = st.text_input("🔎 검색 키워드", placeholder="먹방, 일상 브이로그")
    with r1_c2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()))
    with r1_c3:
        search_mode = st.radio("분석 방식", ["영상 콘텐츠 기반", "채널명 기반"], horizontal=True)

    r2_c1, r2_c2, r2_c3 = st.columns(3)
    with r2_c1:
        selected_sub_range = st.selectbox("🎯 구독자 범위 선택", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_c2:
        efficiency_target = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30) / 100
    with r2_c3:
        max_res = st.number_input("🔍 분석 샘플 수 (키워드당)", 5, 50, 20)
    
    submit_button = st.form_submit_button("🚀 통합 검색 시작")

st.markdown("---")

# --- [5. 하이브리드 로직 함수들] ---

def extract_email_hybrid(desc):
    if not desc or len(desc.strip()) < 5: return "직접 확인 필요"
    reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
    if reg: return reg[0]
    try:
        time.sleep(0.5)
        track_points(1, is_ai=True)
        prompt = f"다음 텍스트에서 비즈니스 메일을 찾아줘. 없으면 'None': {desc}"
        res = model.generate_content(prompt).text.strip()
        return res if "@" in res else "직접 확인 필요"
    except: return "데이터 확인 필요"

def check_performance(up_id, subs):
    if not (min_subs <= subs <= max_subs): return False, 0, 0
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
        return (eff >= efficiency_target), avg_v, eff
    except: return False, 0, 0

def get_year_ad_history(up_id):
    one_year_ago = (datetime.utcnow() - timedelta(days=365)).isoformat() + "Z"
    all_ads = []
    next_token = None
    patterns = ["유료 광고 포함", "Paid promotion", "협찬", "#광고", "AD"]
    
    with st.spinner("최근 1년 치 영상을 전수 조사 중..."):
        while True:
            req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=50, pageToken=next_token).execute()
            track_points(1)
            v_ids = []
            for item in req.get('items', []):
                if item['snippet']['publishedAt'] < one_year_ago:
                    next_token = None
                    break
                v_ids.append(item['contentDetails']['videoId'])
            
            if v_ids:
                v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
                track_points(1)
                for v in v_res.get('items', []):
                    title, desc = v['snippet']['title'], v['snippet'].get('description', '')
                    if any(p in title or p in desc[:300] for p in patterns):
                        all_ads.append({
                            "영상 제목": title, "업로드 일자": v['snippet']['publishedAt'][:10],
                            "조회수": int(v['statistics'].get('viewCount', 0)),
                            "영상 링크": f"https://youtu.be/{v['id']}"
                        })
            next_token = req.get('nextPageToken')
            if not next_token: break
    return pd.DataFrame(all_ads)

# --- [6. 실행 프로세스] ---
if submit_button:
    if not keywords_input:
        st.warning("⚠️ 키워드를 입력해주세요.")
    else:
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        processed_channels = set()
        prog = st.progress(0)
        curr = 0
        total = len(kws) * max_res

        with st.status(f"🔍 {selected_country} 데이터 분석 중...", expanded=True) as status:
            for kw in kws:
                mode_type = "video" if "영상" in search_mode else "channel"
                search = YOUTUBE.search().list(q=kw, part="snippet", type=mode_type, maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                track_points(100)
                
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    ch_id = item['snippet']['channelId']
                    if ch_id in processed_channels: continue
                    processed_channels.add(ch_id)
                    
                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=ch_id).execute()['items'][0]
                        track_points(1)
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        is_ok, avg_v, eff = check_performance(ch['contentDetails']['relatedPlaylists']['uploads'], subs)
                        if is_ok:
                            final_list.append({
                                "채널명": ch['snippet']['title'], "구독자": subs, "평균조회수": round(avg_v),
                                "효율": f"{eff*100:.1f}%", "이메일": extract_email_hybrid(ch['snippet']['description']),
                                "URL": f"https://youtube.com/channel/{ch_id}",
                                "프로필": ch['snippet']['thumbnails']['default']['url'], "upload_id": ch['contentDetails']['relatedPlaylists']['uploads']
                            })
                    except: continue
            status.update(label="✅ 분석 완료!", state="complete")
        st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 및 딥리서치] ---
if "search_results" in st.session_state and not st.session_state.search_results.empty:
    st.subheader("📊 통합 분석 결과")
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "프로필": st.column_config.ImageColumn("프로필"), 
            "URL": st.column_config.LinkColumn("링크", display_text="바로가기"), 
            "upload_id": None
        },
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        st.markdown("---")
        st.subheader(f"📅 '{ch_info['채널명']}' 1년 광고 히스토리")
        ad_df = get_year_ad_history(ch_info['upload_id'])
        if not ad_df.empty:
            st.success(f"🎯 지난 1년간 총 {len(ad_df)}개의 광고/협업 영상이 발견되었습니다.")
            st.dataframe(
                ad_df, 
                column_config={
                    "영상 링크": st.column_config.LinkColumn("링크", display_text="바로가기"), 
                    "조회수": st.column_config.NumberColumn(format="%d회")
                }, 
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("🧐 최근 1년 이내에 감지된 광고 영상이 없습니다.")
