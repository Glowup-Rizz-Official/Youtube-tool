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
COUNTRIES = {
    "대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", 
    "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"
}

SUB_RANGES = {
    "전체": (0, 100000000),
    "1만 미만": (0, 10000),
    "1만 ~ 5만": (10000, 50000),
    "5만 ~ 10만": (50000, 100000),
    "10만 ~ 50만": (100000, 500000),
    "50만 ~ 100만": (500000, 1000000),
    "100만 이상": (1000000, 100000000)
}

# 섭외 메일 멀티 템플릿 설정
TEMPLATES = {
    "템플릿 1 (공식 협업 제안)": {
        "title": "[Glowup Rizz] {name}님, 브랜드 파트너십 협업 제안드립니다.",
        "body": """안녕하세요, <b>{name}</b>님!<br><br>
Glowup Rizz 브랜드 커뮤니케이션 팀입니다.<br>
평소 채널의 콘텐츠를 인상 깊게 보아 저희 브랜드와 결이 잘 맞으실 것 같아 연락드렸습니다.<br><br>
저희는 현재 새로운 캠페인을 준비 중이며, {name}님과 함께 긍정적인 시너지를 내고 싶습니다.<br>
아래 링크를 통해 저희 브랜드 소개를 확인해 보실 수 있습니다.<br><br>
🔗 <a href='https://glowuprizz.com'>Glowup Rizz 브랜드 소개서 보기</a><br><br>
긍정적인 검토 부탁드리며, 답장 주시면 상세 제안서를 보내드리겠습니다.<br><br>
감사합니다.<br>
<b>Glowup Rizz 드림</b>"""
    },
    "템플릿 2 (제품 협찬/리뷰)": {
        "title": "[제품협찬] {name}님, 신제품 리뷰 및 광고 제안드립니다.",
        "body": """안녕하세요 <b>{name}</b>님!<br><br>
이번에 저희 Glowup Rizz에서 출시된 신제품의 리뷰 협업을 제안드리고자 합니다.<br>
{name}님의 전문적인 리뷰 스타일이 저희 제품을 가장 잘 표현해주실 것 같습니다.<br><br>
단순 제품 제공 외에 별도의 원고료 협의도 가능하오니 관심 있으시면 회신 부탁드립니다.<br><br>
감사합니다!"""
    },
    "테스트용 (내 메일 전송)": {
        "title": "[TEST] 메일 발송 기능 테스트 - {name} 채널용",
        "body": "이 메일은 <b>발송 기능 테스트</b>용입니다.<br>링크가 파랗게 보이는지 확인하세요: <a href='https://google.com'>테스트 링크</a>"
    }
}

# --- [3. UI 설정] ---
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        pass
    st.markdown("---")
    st.info("🚀 **Glowup Rizz v4.7**\n이메일 자동화 시스템 가동")
    
    # 발송 로그 확인 기능
    if st.checkbox("📋 최근 메일 발송 로그 보기"):
        st.markdown("### 최근 10건 발송 결과")
        try:
            conn = sqlite3.connect('mail_log.db')
            log_df = pd.read_sql_query("SELECT * FROM send_log ORDER BY sent_at DESC LIMIT 10", conn)
            st.dataframe(log_df, use_container_width=True)
            conn.close()
        except:
            st.write("아직 발송 기록이 없습니다.")

st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [4. 로직 함수들 (기존 + 신규)] ---

def init_db():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS send_log 
                 (channel_name TEXT, email TEXT, status TEXT, sent_at TEXT)''')
    conn.commit()
    conn.close()

def save_log(name, email, status):
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO send_log VALUES (?, ?, ?, ?)", (name, email, status, now))
    conn.commit()
    conn.close()

def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def send_html_mail(receiver_email, subject, html_body, channel_name):
    if not is_valid_email(receiver_email):
        return False, "이메일 형식이 유효하지 않습니다."
    
    msg = MIMEText(html_body, 'html')
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PW)
            server.sendmail(EMAIL_USER, receiver_email, msg.as_string())
        save_log(channel_name, receiver_email, "성공")
        return True, "성공"
    except Exception as e:
        save_log(channel_name, receiver_email, f"실패: {str(e)}")
        return False, str(e)

# (기존 유튜버 분석 함수들: extract_exclude_list, extract_email_ai, check_performance, get_recent_ad_videos_ai 유지)
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
        time.sleep(1)
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "AI 분석 어려움 (직접 확인 필요)"
    except Exception as e:
        if "429" in str(e): return "AI 일시 중단 (잠시 후 시도)"
        return "데이터 확인 필요"

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
            prompt = f"다음 중 공식 표기는 없으나 광고 협업이 의심되는 인덱스만 골라줘. 없으면 'None'.\n\n{video_text}"
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

# DB 초기화 실행
init_db()

# --- [5. 메인 검색 폼] ---
with st.form("search_form"):
    st.markdown("📥 **기존 리스트 제외하기 (선택 사항)**")
    exclude_file = st.file_uploader("이미 확보한 채널 리스트(엑셀/CSV)를 업로드하면 제외됩니다.", type=['xlsx', 'csv'])
    st.markdown("---")
    r1_col1, r1_col2, r1_col3 = st.columns([4, 1.2, 0.8])
    with r1_col1:
        keywords_input = st.text_input("🔎 검색 키워드", placeholder="먹방, 일상 브이로그 등", label_visibility="collapsed")
    with r1_col2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()), label_visibility="collapsed")
    with r1_col3:
        submit_button = st.form_submit_button("🚀 검색")
    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        search_mode = st.radio("분석 방식", ["영상 콘텐츠 기반 (추천)", "채널명 기반"], horizontal=True)
        selected_sub_range = st.selectbox("🎯 구독자 범위", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2:
        efficiency_target = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30) / 100
    with r2_col3:
        max_res = st.number_input("🔍 분석 샘플 수", 5, 50, 20)

st.markdown("---")

# --- [6. 실행 프로세스] ---
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if submit_button:
    if not keywords_input:
        st.warning("⚠️ 키워드를 입력해주세요.")
    else:
        exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        prog = st.progress(0); curr = 0; total = len(kws) * max_res; processed_channels = set()
        with st.status(f"🔍 {search_mode} 분석 중...", expanded=True) as status:
            for kw in kws:
                if "영상 콘텐츠" in search_mode:
                    search = YOUTUBE.search().list(q=kw, part="snippet", type="video", maxResults=max_res, regionCode=COUNTRIES[selected_country], videoDuration="medium").execute()
                else:
                    search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                for item in search['items']:
                    curr += 1; prog.progress(min(curr/total, 1.0))
                    ch_id = item['snippet']['channelId']
                    if ch_id in processed_channels: continue
                    processed_channels.add(ch_id)
                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=ch_id).execute()['items'][0]
                        title = ch['snippet']['title']; channel_url = f"https://youtube.com/channel/{ch_id}"
                        if title.strip() in exclude_data or channel_url in exclude_data: continue
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        if is_ok:
                            final_list.append({"채널명": title, "구독자": subs, "평균 조회수": round(avg_v), "효율": f"{eff*100:.1f}%", "이메일": extract_email_ai(ch['snippet']['description']), "URL": channel_url, "프로필": ch['snippet']['thumbnails']['default']['url'], "upload_id": up_id})
                    except: continue
            status.update(label="✅ 분석 완료!", state="complete", expanded=False)
        st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 출력 및 섭외 자동화 영역] ---
if isinstance(st.session_state.search_results, pd.DataFrame) and not st.session_state.search_results.empty:
    st.subheader("📊 분석 결과 (채널을 클릭하여 섭외를 시작하세요)")
    event = st.dataframe(
        st.session_state.search_results,
        column_config={"프로필": st.column_config.ImageColumn("프로필"), "URL": st.column_config.LinkColumn("링크", display_text="바로가기"), "upload_id": None},
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        
        st.markdown("---")
        # 섭외 자동화 섹션
        st.subheader(f"📧 '{ch_info['채널명']}' 크리에이터 섭외 대시보드")
        
        mail_col1, mail_col2 = st.columns([3, 1])
        with mail_col1:
            # 이메일 더블체크 및 수정 가능
            target_email = st.text_input("수신 이메일 (AI 추출 결과)", value=ch_info['이메일'])
            if not is_valid_email(target_email):
                st.error("⚠️ 이메일 주소가 올바르지 않습니다. 가짜 메일이거나 형식이 잘못되었을 수 있습니다.")
            else:
                st.success("✅ 유효한 이메일 형식입니다.")
        
        # 템플릿 선택 및 제목/본문 편집
        selected_tpl_name = st.selectbox("사용할 섭외 템플릿 선택", list(TEMPLATES.keys()))
        tpl = TEMPLATES[selected_tpl_name]
        
        final_subject = st.text_input("메일 제목 (수정 가능)", value=tpl["title"].format(name=ch_info['채널명']))
        final_body_html = st.text_area("메일 본문 (HTML 태그 가능: <b>, <a href=''> 등)", 
                                       value=tpl["body"].format(name=ch_info['채널명']), height=250)
        
        # 미리보기
        with st.expander("👀 실제 발송될 메일 미리보기"):
            st.markdown(f"**제목:** {final_subject}")
            st.markdown("---")
            st.html(final_body_html) # HTML 렌더링 미리보기
            
        if st.button(f"🚀 {selected_tpl_name} 발송하기"):
            with st.spinner("서버를 통해 메일을 발송 중입니다..."):
                success, msg = send_html_mail(target_email, final_subject, final_body_html, ch_info['채널명'])
                if success:
                    st.success(f"✅ {ch_info['채널명']}님께 메일이 성공적으로 전송되었습니다!")
                else:
                    st.error(f"❌ 발송 실패: {msg}")

        # 기존 광고 딥리서치 영역
        st.markdown("---")
        st.subheader(f"🔍 '{ch_info['채널명']}' AI 광고 딥리서치")
        col_v1, col_v2 = st.columns([1, 3])
        with col_v1:
            analysis_count = st.selectbox("분석 범위 설정", [10, 20, 30], index=1)
        with st.spinner(f"최근 {analysis_count}개 영상 분석 중..."):
            ad_df = get_recent_ad_videos_ai(ch_info['upload_id'], analysis_count)
            if not ad_df.empty:
                st.success(f"🎯 총 {len(ad_df)}개의 광고/협업 영상이 감지되었습니다.")
                st.dataframe(ad_df, column_config={"영상 링크": st.column_config.LinkColumn("링크", display_text="바로가기"), "조회수": st.column_config.NumberColumn(format="%d회")}, use_container_width=True, hide_index=True)
            else:
                st.warning("🧐 최근 광고 협업 영상이 감지되지 않았습니다.")
