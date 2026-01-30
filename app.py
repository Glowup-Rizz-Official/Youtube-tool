import streamlit as st
import pandas as pd
import re
import base64
import time
import sqlite3
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import googleapiclient.discovery
import googleapiclient.errors
import google.generativeai as genai

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
    # 이메일 발송용 보안 설정 추가
    EMAIL_USER = st.secrets["EMAIL_USER"]
    EMAIL_PW = st.secrets["EMAIL_PW"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요. (YOUTUBE_API_KEY, GEMINI_API_KEY, EMAIL_USER, EMAIL_PW 필요)")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. 데이터 및 템플릿 설정] ---
COUNTRIES = {"대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"}
SUB_RANGES = {"전체": (0, 100000000), "1만 미만": (0, 10000), "1만 ~ 5만": (10000, 50000), "5만 ~ 10만": (50000, 100000), "10만 ~ 50만": (100000, 500000), "50만 ~ 100만": (500000, 1000000), "100만 이상": (1000000, 100000000)}

# 섭외 메일 멀티 템플릿
TEMPLATES = {
    "템플릿 1 (공식 협업 제안)": {
        "title": "[Glowup Rizz] {name}님, 브랜드 파트너십 협업 제안드립니다.",
        "body": "안녕하세요, <b>{name}</b>님!<br><br>Glowup Rizz 브랜드 커뮤니케이션 팀입니다.<br>콘텐츠를 인상 깊게 보아 협업을 제안드리고자 합니다.<br><br>🔗 <a href='https://glowuprizz.com'>브랜드 소개서 보기</a>"
    },
    "템플릿 2 (제품 협찬/리뷰)": {
        "title": "[제품협찬] {name}님, 신제품 리뷰 및 광고 제안드립니다.",
        "body": "안녕하세요 <b>{name}</b>님!<br><br>신제품 출시 기념 협찬 광고를 제안드립니다.<br>관심 있으시면 회신 부탁드립니다."
    }
}

# --- [3. UI 설정 및 세션 초기화] ---
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

if "search_results" not in st.session_state: st.session_state.search_results = None
if "quota_used" not in st.session_state: st.session_state.quota_used = 0

# --- [4. 로직 함수들] ---
def init_db():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS send_log (channel_name TEXT, email TEXT, status TEXT, sent_at TEXT)')
    conn.commit(); conn.close()

def save_log(name, email, status):
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute("INSERT INTO send_log VALUES (?, ?, ?, ?)", (name, email, status, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit(); conn.close()

def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None

def send_html_mail(receiver_email, subject, html_body, channel_name):
    if not is_valid_email(receiver_email): return False, "이메일 형식 오류"
    msg = MIMEText(html_body, 'html')
    msg['Subject'] = subject; msg['From'] = EMAIL_USER; msg['To'] = receiver_email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PW)
            server.sendmail(EMAIL_USER, receiver_email, msg.as_string())
        save_log(channel_name, receiver_email, "성공"); return True, "성공"
    except Exception as e:
        save_log(channel_name, receiver_email, f"실패: {str(e)}"); return False, str(e)

# (기존 유튜버 분석 함수들 생략 없이 그대로 유지)
def extract_exclude_list(file):
    try:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        exclude_set = set()
        for col in df.columns:
            exclude_set.update(df[col].astype(str).str.strip().tolist())
        return exclude_set
    except: return set()

def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5: return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        time.sleep(1); response = model.generate_content(prompt); res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "AI 분석 어려움 (직접 확인 필요)"
    except: return "데이터 확인 필요"

def check_performance(up_id, subs):
    if not (min_subs <= subs <= max_subs): return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        return (eff >= efficiency_target), avg_v, eff
    except: return False, 0, 0

def get_recent_ad_videos_ai(up_id, count):
    try:
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        all_videos = []; ad_found_indices = []
        official_patterns = ["유료 광고 포함", "Paid promotion", "제작 지원", "협찬", "#광고", "AD"]
        for idx, v in enumerate(v_res.get('items', [])):
            title = v['snippet']['title']; desc = v['snippet'].get('description', '')
            video_data = {"영상 제목": title, "설명": desc[:500], "업로드 일자": datetime.strptime(v['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d'), "조회수": int(v['statistics'].get('viewCount', 0)), "영상 링크": f"https://youtu.be/{v['id']}"}
            if any(p in title or p in desc[:200] for p in official_patterns): ad_found_indices.append(idx)
            all_videos.append(video_data)
        remaining_indices = [i for i in range(len(all_videos)) if i not in ad_found_indices]
        if remaining_indices:
            video_text = "\n".join([f"[{i}] 제목: {all_videos[i]['영상 제목']}" for i in remaining_indices])
            prompt = f"다음 중 공식 표기는 없으나 협업이 의심되는 인덱스만 골라줘. 없으면 'None'.\n\n{video_text}"
            try:
                time.sleep(1); response = model.generate_content(prompt); ai_res = response.text.strip()
                if "None" not in ai_res:
                    ai_indices = [int(i.strip()) for i in ai_res.split(",") if i.strip().isdigit()]
                    ad_found_indices.extend(ai_indices)
            except: pass
        final_indices = sorted(list(set(ad_found_indices)))
        ad_videos = [all_videos[i] for i in final_indices if i < len(all_videos)]
        return pd.DataFrame(ad_videos)[["영상 제목", "업로드 일자", "조회수", "영상 링크"]]
    except: return pd.DataFrame()

init_db()

# --- [5. 사이드바 관리자 및 할당량 모니터링] ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    st.markdown("### 📊 API 리소스 현황")
    st.progress(min(st.session_state.quota_used / 10000, 1.0))
    st.caption(f"YouTube 할당량: {st.session_state.quota_used} / 10,000")
    st.markdown("---")
    admin_pw = st.text_input("🔓 관리자 모드", type="password")
    if admin_pw == "rizz1000":
        st.success("관리자 승인")
        if st.button("🔄 할당량 리셋"): st.session_state.quota_used = 0; st.rerun()
        st.markdown("🔗 [AI 토큰 결제 센터](https://aistudio.google.com/plan)")
        if st.checkbox("📋 메일 발송 로그 보기"):
            conn = sqlite3.connect('mail_log.db'); log_df = pd.read_sql_query("SELECT * FROM send_log ORDER BY sent_at DESC", conn)
            st.dataframe(log_df, use_container_width=True); conn.close()

# --- [6. 메인 검색 폼] ---
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
with st.form("search_form"):
    exclude_file = st.file_uploader("제외 리스트 업로드", type=['xlsx', 'csv'])
    keywords_input = st.text_input("🔎 검색 키워드")
    selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()))
    submit_button = st.form_submit_button("🚀 검색")
    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        search_mode = st.radio("분석 방식", ["영상 콘텐츠 기반 (추천)", "채널명 기반"], horizontal=True)
        selected_sub_range = st.selectbox("🎯 구독자 범위", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2: efficiency_target = st.slider("📈 최소 효율 (%)", 0, 100, 30) / 100
    with r2_col3: max_res = st.number_input("🔍 분석 샘플 수", 5, 50, 20)

# 검색 실행 로직 (검색 시 할당량 100 가산)
if submit_button and keywords_input:
    st.session_state.quota_used += 100
    exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
    kws = [k.strip() for k in keywords_input.split(",")]
    final_list = []
    prog = st.progress(0); curr = 0; total = len(kws) * max_res; processed = set()
    with st.status("🔍 분석 및 필터링 중...") as status:
        for kw in kws:
            if "영상 콘텐츠" in search_mode:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="video", maxResults=max_res, regionCode=COUNTRIES[selected_country], videoDuration="medium").execute()
            else:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
            for item in search['items']:
                curr += 1; prog.progress(min(curr/total, 1.0))
                ch_id = item['snippet']['channelId']
                if ch_id in processed: continue
                processed.add(ch_id)
                try:
                    ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=ch_id).execute()['items'][0]
                    title = ch['snippet']['title']; url = f"https://youtube.com/channel/{ch_id}"
                    if title.strip() in exclude_data or url in exclude_data: continue
                    subs = int(ch['statistics'].get('subscriberCount', 0))
                    up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                    is_ok, avg_v, eff = check_performance(up_id, subs)
                    if is_ok:
                        final_list.append({"채널명": title, "구독자": subs, "평균 조회수": round(avg_v), "효율": f"{eff*100:.1f}%", "이메일": extract_email_ai(ch['snippet']['description']), "URL": url, "프로필": ch['snippet']['thumbnails']['default']['url'], "upload_id": up_id})
                except: continue
        status.update(label="✅ 분석 완료!", state="complete")
    st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 출력 및 섭외 통합 대시보드] ---
if st.session_state.search_results is not None:
    st.subheader("📊 분석 결과")
    event = st.dataframe(st.session_state.search_results, column_config={"프로필": st.column_config.ImageColumn("프로필"), "URL": st.column_config.LinkColumn("링크", display_text="바로가기"), "upload_id": None}, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        
        # 1단계: AI 광고 딥리서치
        st.markdown("---")
        st.subheader(f"🔍 '{ch_info['채널명']}' AI 광고 딥리서치")
        analysis_count = st.selectbox("분석 범위", [10, 20, 30], index=1)
        with st.spinner("AI가 협업 사례 분석 중..."):
            ad_df = get_recent_ad_videos_ai(ch_info['upload_id'], analysis_count)
            if not ad_df.empty: st.dataframe(ad_df, use_container_width=True, hide_index=True)
            else: st.warning("감지된 광고 없음")
        
        # 2단계: 섭외 메일 발송 영역 (딥리서치 바로 아래 배치)
        st.markdown("---")
        st.subheader(f"📧 '{ch_info['채널명']}' 섭외 메일 전송")
        
        m_col1, m_col2 = st.columns([3, 1])
        with m_col1:
            t_email = st.text_input("수신 메일", value=ch_info['이메일'])
            if not is_valid_email(t_email): st.error("이메일 형식 확인 필요")
        
        sel_tpl = st.selectbox("템플릿 선택", list(TEMPLATES.keys()))
        tpl = TEMPLATES[sel_tpl]
        f_sub = st.text_input("메일 제목", value=tpl["title"].format(name=ch_info['채널명']))
        f_body = st.text_area("메일 본문 (HTML 가능)", value=tpl["body"].format(name=ch_info['채널명']), height=200)
        
        with st.expander("👀 메일 미리보기"):
            st.markdown(f"**제목:** {f_sub}")
            st.html(f_body)
            
        if st.button(f"🚀 {sel_tpl} 발송하기"):
            with st.spinner("발송 중..."):
                ok, msg = send_html_mail(t_email, f_sub, f_body, ch_info['채널명'])
                if ok: st.success("✅ 메일 발송 성공!")
                else: st.error(f"❌ 실패: {msg}")
