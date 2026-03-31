import streamlit as st
import pandas as pd
import re
import time
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

# --- [2. 데이터 및 상수 설정] ---
COUNTRIES = {"대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"}
SUB_RANGES = {"전체": (0, 100000000), "1만 미만": (0, 10000), "1만 ~ 5만": (10000, 50000), "5만 ~ 10만": (50000, 100000), "10만 ~ 50만": (100000, 500000), "50만 ~ 100만": (500000, 1000000), "100만 이상": (1000000, 100000000)}

# [수정됨] 요청하신 열 순서 및 명칭으로 변경
COLUMN_ORDER = [
    "닉네임", "유튜브 계정", "인스타그램 계정", "블로그 계정", "틱톡 계정", "이메일", 
    "조회수", "좋아요", "댓글", "팔로워", "ER(%)", 
    "프로필", "upload_id", "효율" # UI 표시 및 내부 기능을 위한 데이터
]

# --- [3. DB 및 공유 상태 관리] ---
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

if "search_results" not in st.session_state: st.session_state.search_results = None

def init_db():
    conn = sqlite3.connect('mail_log.db')
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

# --- [4. 핵심 로직 함수들] ---
def get_kst_now():
    return datetime.now(timezone.utc) + timedelta(hours=9)

def manage_api_quota(yt_add=0, ai_add=0):
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute("SELECT youtube_count, ai_count, last_reset FROM api_usage WHERE id=1")
    row = c.fetchone()
    yt_current, ai_current, last_reset_str = row
    
    now_kst = get_kst_now()
    last_reset_kst = datetime.strptime(last_reset_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=9))) if last_reset_str else now_kst
    today_5pm = now_kst.replace(hour=17, minute=0, second=0, microsecond=0)
    reset_threshold = today_5pm - timedelta(days=1) if now_kst < today_5pm else today_5pm
        
    if last_reset_kst < reset_threshold:
        yt_current = 0
        c.execute("UPDATE api_usage SET youtube_count = 0, last_reset = ? WHERE id=1", 
                  (now_kst.strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
    
    if yt_add > 0 or ai_add > 0:
        c.execute("UPDATE api_usage SET youtube_count = youtube_count + ?, ai_count = ai_count + ? WHERE id=1", 
                  (yt_add, ai_add))
        conn.commit()
        yt_current += yt_add
        ai_current += ai_add
        
    conn.close()
    return yt_current, ai_current

def reset_ai_quota():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute("UPDATE api_usage SET ai_count = 0 WHERE id=1")
    conn.commit()
    conn.close()

def extract_exclude_list(file):
    try:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        return set(df.iloc[:,0].astype(str).str.strip().tolist())
    except: return set()

def extract_email_ai(desc):
    if not desc or len(desc) < 5: return ""
    try:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
        if emails: return emails[0]
        manage_api_quota(ai_add=1)
        response = model.generate_content(f"다음 텍스트에서 이메일 주소만 추출해. 없으면 빈칸 출력: {desc}")
        res = response.text.strip()
        return res if "@" in res else ""
    except: return ""

# [수정됨] 쇼츠 위주 판별 및 15개/25개 유동적 ER 계산 로직
def check_performance_and_er(up_id, subs):
    try:
        manage_api_quota(yt_add=1)
        # 판별을 위해 일단 최근 25개 영상을 가져옵니다.
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=25).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        if not v_ids: return False, 0, 0, 0, 0, 0
        
        manage_api_quota(yt_add=1)
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        
        # 쇼츠 판별: duration에 'M'(분)이나 'H'(시간)가 없으면 쇼츠(60초 미만)로 간주
        shorts_count = sum(1 for v in v_res['items'] if 'M' not in v['contentDetails']['duration'] and 'H' not in v['contentDetails']['duration'])
        
        # 최근 25개 영상 중 쇼츠가 절반(13개) 이상이면 '쇼츠 위주 채널'로 판별
        is_shorts_focused = shorts_count > (len(v_res['items']) / 2)
        
        # 쇼츠 위주면 25개 모두 사용, 아니면 최근 15개만 잘라서 사용
        target_videos = v_res['items'] if is_shorts_focused else v_res['items'][:15]
        
        if not target_videos: return False, 0, 0, 0, 0, 0
        
        total_views = sum(int(v['statistics'].get('viewCount', 0)) for v in target_videos)
        total_likes = sum(int(v['statistics'].get('likeCount', 0)) for v in target_videos)
        total_comments = sum(int(v['statistics'].get('commentCount', 0)) for v in target_videos)
        
        avg_v = total_views / len(target_videos)
        eff = avg_v / subs if subs > 0 else 0
        er = ((total_likes + total_comments) / total_views * 100) if total_views > 0 else 0
        
        return True, avg_v, total_likes, total_comments, er, eff
    except: return False, 0, 0, 0, 0, 0

def get_recent_ad_videos_ai(up_id, count):
    try:
        manage_api_quota(yt_add=2)
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        all_videos = []
        ad_indices = []
        patterns = ["유료 광고", "협찬", "광고", "AD", "Paid", "제작 지원", "제품 제공"]
        
        for idx, v in enumerate(v_res.get('items', [])):
            title = v['snippet']['title']
            desc = v['snippet'].get('description', '')
            pub = v['snippet']['publishedAt']
            if (datetime.now() - datetime.strptime(pub, '%Y-%m-%dT%H:%M:%SZ')).days > 365: continue
            
            vid_data = {
                "영상 제목": title, 
                "업로드": pub[:10], 
                "조회수": int(v['statistics'].get('viewCount',0)), 
                "링크": f"https://youtu.be/{v['id']}" 
            }
            if any(p in title for p in patterns) or any(p in desc for p in patterns):
                ad_indices.append(idx)
            all_videos.append(vid_data)
            
        remaining = [i for i in range(len(all_videos)) if i not in ad_indices]
        if remaining:
            prompt = "".join([f"[{i}] 제목:{all_videos[i]['영상 제목']} / 설명:{v_res['items'][i]['snippet']['description'][:300]}\n" for i in remaining])
            try:
                manage_api_quota(ai_add=1)
                resp = model.generate_content(f"광고/협업이 의심되는 번호만 쉼표로 출력:\n{prompt}")
                ad_indices.extend([int(x) for x in re.findall(r'\d+', resp.text)])
            except: pass
        final_ads = [all_videos[i] for i in sorted(list(set(ad_indices))) if i < len(all_videos)]
        return pd.DataFrame(final_ads)
    except: return pd.DataFrame()

# --- [5. 사이드바 UI: 관리자 및 로그 확인] ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    
    # 1. 리소스 현황
    yt_used, ai_used = manage_api_quota()
    st.markdown("### 📊 팀 전체 리소스 현황")
    
    yt_limit = 500000 
    st.progress(min(yt_used / yt_limit, 1.0))
    st.caption(f"📺 YouTube API: {yt_used:,} / {yt_limit:,} (오늘 5PM 리셋)")
    
    st.markdown("---")
    st.write(f"🤖 **AI API 호출 횟수:** {ai_used:,}회")
            
    st.markdown("---")
    
    # 2. 관리자 모드
    admin_pw = st.text_input("🔓 관리자 모드", type="password")
    
    try:
        secret_pw = st.secrets["ADMIN_PASSWORD"]
    except:
        secret_pw = "rizz" 

    if admin_pw == secret_pw:
        st.success("✅ 관리자 인증 완료")
        if st.button("🔄 AI 카운트 리셋 (월초 권장)"):
            reset_ai_quota()
            st.rerun()

# --- [6. 메인 검색 UI] ---
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
with st.form("search"):
    exclude_file = st.file_uploader("제외할 채널 리스트", type=['xlsx', 'csv'])
    kws = st.text_input("검색 키워드 (쉼표 구분)")
    
    c1, c2, c3 = st.columns(3)
    with c1: selected_country = st.selectbox("국가", list(COUNTRIES.keys()))
    with c2: 
        sub_range = st.selectbox("구독자 범위", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[sub_range]
    with c3: max_res = st.number_input("분석 샘플 수", 5, 50, 20)
    
    c4, c5 = st.columns(2)
    with c4: search_mode = st.radio("검색 방식", ["영상 기반 (추천)", "채널명 기반"], horizontal=True)
    with c5: eff_target = st.slider("최소 효율 (%)", 0, 100, 30) / 100
    
    btn = st.form_submit_button("🚀 분석 시작")

if btn and kws:
    manage_api_quota(yt_add=100)
    exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
    keywords = [k.strip() for k in kws.split(",")]
    final_list = []
    processed = set()
    prog = st.progress(0)
    curr = 0
    total = len(keywords) * max_res
    
    for kw in keywords:
        try:
            if "영상" in search_mode:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="video", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
            else:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                
            for item in search['items']:
                curr += 1
                prog.progress(min(curr/total, 1.0))
                cid = item['snippet']['channelId']
                if cid in processed: continue
                processed.add(cid)
                
                ch_res = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=cid).execute()
                if not ch_res['items']: continue
                ch = ch_res['items'][0]
                
                title = ch['snippet']['title']
                url = f"https://youtube.com/channel/{cid}"
                if title in exclude_data or url in exclude_data: continue
                
                subs = int(ch['statistics'].get('subscriberCount', 0))
                if not (min_subs <= subs <= max_subs): continue
                
                upid = ch['contentDetails']['relatedPlaylists']['uploads']
                
                is_ok, avg_v, t_likes, t_comments, er_val, eff = check_performance_and_er(upid, subs)
                
                if is_ok and eff >= eff_target:
                    email = extract_email_ai(ch['snippet']['description'])
                    
                    # [수정됨] 변경된 열 순서에 맞게 데이터 삽입
                    row_data = {
                        "닉네임": title,
                        "유튜브 계정": url,
                        "인스타그램 계정": "",
                        "블로그 계정": "",
                        "틱톡 계정": "",
                        "이메일": email,
                        "조회수": int(avg_v),
                        "좋아요": int(t_likes),
                        "댓글": int(t_comments),
                        "팔로워": subs,
                        "ER(%)": round(er_val, 2),
                        "프로필": ch['snippet']['thumbnails']['default']['url'],
                        "upload_id": upid,
                        "효율": eff 
                    }
                    final_list.append(row_data)
        except: break
    
    st.session_state.search_results = pd.DataFrame(final_list, columns=COLUMN_ORDER)

# --- [7. 결과 및 딥리서치 UI] ---
if "search_results" in st.session_state and st.session_state.search_results is not None:
    st.subheader("📊 분석 결과 리스트 (결과를 클릭하면 하단에서 딥리서치가 가능합니다)")
    
    # [수정됨] URL -> 유튜브 계정으로 변경
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "프로필": st.column_config.ImageColumn(),
            "유튜브 계정": st.column_config.LinkColumn("유튜브 계정", display_text="이동"),
            "upload_id": None,
            "효율": None,
            "ER(%)": st.column_config.NumberColumn(format="%.2f%%")
        },
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if not st.session_state.search_results.empty:
        csv = st.session_state.search_results.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 전체 관리 대장 다운로드 (CSV)", csv, "creator_list.csv", "text/csv")

    if event.selection.rows:
        row = st.session_state.search_results.iloc[event.selection.rows[0]]
        st.divider()
        
        # [A] 딥리서치 (기존 기능 완벽 유지)
        st.subheader(f"🔍 '{row['닉네임']}' 딥리서치")
        if st.button("광고 이력 분석 시작"):
            with st.spinner("분석 중..."):
                df = get_recent_ad_videos_ai(row['upload_id'], 20)
                if not df.empty:
                    st.error(f"🚨 광고 의심 영상 {len(df)}개 발견")
                    st.dataframe(
                        df, 
                        column_config={"링크": st.column_config.LinkColumn("영상 바로가기", display_text="시청")},
                        use_container_width=True
                    )
                else: st.success("✅ 최근 1년 내 광고 이력 없음")
