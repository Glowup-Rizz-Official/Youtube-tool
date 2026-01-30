import streamlit as st
import pandas as pd
import re
import time
import sqlite3
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import googleapiclient.discovery
import googleapiclient.errors
import google.generativeai as genai

from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage     
# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
    EMAIL_USER = st.secrets["EMAIL_USER"]
    EMAIL_PW = st.secrets["EMAIL_PW"]
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

# 섭외 템플릿
TEMPLATES = {
    "템플릿 1 (아정당 협업 제안)": {
        "title": "[글로우업리즈 X {name}] 아정당 광고 제안의 건",
        "body": """안녕하세요, {name}님!<br>
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.<br><br>

평소 {name}님 채널의 유익한 컨텐츠 모두 즐겨보고 있습니다!<br>
다름이 아니라 이번에 아래 브랜드를 제안 드리고자 연락 드렸습니다.<br>
<hr>
제안드리는 광고 <b>[아정당]</b> 광고입니다.<br>
아정당은 인터넷, 정수기, 휴대폰, TV 등 가전제품을 교체하면<br>
최대 128만원의 지원금 혜택을 받을 수 있는 홈서비스 플랫폼입니다.<br><br>

원빈님께서 광고모델로 운영되고 있으며 많은 크리에이터분들과 협업을 진행 중인 브랜드입니다.<br><br>

다만 해당 광고의 경우 경험의 의한 자연스러운 소구를 원칙으로 하고 있어<br>
직접 휴대폰, 인터넷, TV, 정수기 중 한 품목을 교체 가능한지 문의 드립니다.<br>
(해당 과정에서 발생하는 비용은 모두 저희가 부담 할 예정입니다.)
<hr>
협업 가능성을 논의하고자, 광고 단가에 대해 아래와 같이 문의하고자 합니다.<br><br>

<b>① 브랜디드 광고</b><br>
<b>② PPL</b><br>
<b>③ 릴스/쇼츠 광고</b><br>
<b>④ 진행 가능한 날짜</b><br><br>

관련하여 문의사항이 있으시다면 편하게 말씀 부탁드립니다.<br><br>

감사합니다.<br>
{sender} 드림"""
    },
    "템플릿 2 (휙/보바 협업 제안)": {
        "title": "[글로우업리즈 X {name}] 휙, 보바 광고 제안의 건",
        "body": """안녕하세요, {name} 계정 담당자님!<br>
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.<br><br>

평소 {name} 프로필의 다양한 콘텐츠 모두 즐겨보고 있습니다!<br>
다름이 아니라 이번에 아래 두 브랜드 광고를 제안 드리고자 연락 드렸습니다.<br>
* 아래 제품들 이외에 내부에 다른 제품도 많으니, 궁금하신 사항이 있으시다면 언제든 편하게 연락주세요!<br><br>

<b>1. 대한민국 보조배터리 1위 브랜드 <a href='https://vova.co.kr' target='_blank'>[보바 홈페이지]</a></b><br>
- 동급 대비 가장 가벼운 보조배터리, 언제 어디서나 부담 없이 휴대 가능<br>
- 대형 유튜버들이 직접 사용하고 추천하는 믿을 수 있는 제품!<br>
- 아이디어: 일상, 여행 vlog 콘텐츠로 이동 중 제품 사용 및 데일리 필수템 소개<br><br>

<b>2. 고속 헤어 스타일러 <a href='https://wheek.co.kr/' target='_blank'>[휙 홈페이지]</a></b><br>
- 다ㅇ슨, 샤ㅇ 등 고급 스타일러와 동급 성능임에도 10만원 초반대 가성비<br>
- 헤어디바이스 최초 임상까지 완료된 믿을 수 있는 제품<br>
- 아이디어: 모닝/나이트 루틴, 뷰티 콘텐츠로 스타일링 추천
<hr>
&lt;제안&gt;<br>
1. 광고비 형태<br>
2. 광고비+RS 방식 (수수료 방식으로 더 많은 수익 창출 가능)
<hr>
협업 가능성을 논의하고자, 광고 단가에 대해 아래와 같이 문의하고자 합니다.<br><br>

<b>① 브랜디드 광고</b><br>
<b>② PPL</b><br>
<b>③ 릴스/쇼츠 광고</b><br>
<b>④ RS 진행 여부</b><br>
<b>⑤ 진행 가능한 날짜</b><br><br>

제품을 먼저 보내드릴 수도 있으니 편하게 말씀 부탁드립니다.<br>
궁금하신 사항은 편하게 해당 연락처로 연락 부탁드립니다.<br><br>

감사합니다.<br>
{sender} 드림."""
    }
}

# --- [3. DB 및 공유 상태 관리] ---
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

if "search_results" not in st.session_state: st.session_state.search_results = None

def init_db():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    # 이메일 로그 테이블
    c.execute('CREATE TABLE IF NOT EXISTS send_log (channel_name TEXT, email TEXT, status TEXT, sent_at TEXT)')
    # API 사용량 테이블 (날짜, 유튜브사용량, AI사용량, 마지막업데이트시간)
    c.execute('''CREATE TABLE IF NOT EXISTS api_usage 
                 (id INTEGER PRIMARY KEY, youtube_count INTEGER, ai_count INTEGER, last_reset TEXT)''')
    # 초기 행 생성
    c.execute("SELECT count(*) FROM api_usage")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO api_usage (id, youtube_count, ai_count, last_reset) VALUES (1, 0, 0, ?)", 
                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    conn.commit()
    conn.close()

init_db()

# --- [4. 핵심 로직 함수들] ---

def get_kst_now():
    # 한국 시간(KST) = UTC+9
    return datetime.now(timezone.utc) + timedelta(hours=9)

def manage_api_quota(yt_add=0, ai_add=0):
    """팀원 공유 API 사용량 관리 및 자동 리셋 로직"""
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    
    # 현재 상태 조회
    c.execute("SELECT youtube_count, ai_count, last_reset FROM api_usage WHERE id=1")
    row = c.fetchone()
    yt_current, ai_current, last_reset_str = row
    
    # 한국 시간 기준 리셋 로직 (오후 5시)
    now_kst = get_kst_now()
    last_reset_kst = datetime.strptime(last_reset_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=9))) if last_reset_str else now_kst
    
    # 오늘의 오후 5시 구하기
    today_5pm = now_kst.replace(hour=17, minute=0, second=0, microsecond=0)
    if now_kst < today_5pm:
        # 지금이 5시 전이면, 리셋 기준은 어제 5시
        reset_threshold = today_5pm - timedelta(days=1)
    else:
        # 지금이 5시 후면, 리셋 기준은 오늘 5시
        reset_threshold = today_5pm
        
    # 마지막 리셋 시간이 기준 시간보다 이전이면 리셋 수행
    if last_reset_kst < reset_threshold:
        yt_current = 0
        # 리셋 시간 업데이트
        c.execute("UPDATE api_usage SET youtube_count = 0, last_reset = ? WHERE id=1", 
                  (now_kst.strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
    
    # 사용량 추가
    if yt_add > 0 or ai_add > 0:
        c.execute("UPDATE api_usage SET youtube_count = youtube_count + ?, ai_count = ai_count + ? WHERE id=1", 
                  (yt_add, ai_add))
        conn.commit()
        yt_current += yt_add
        ai_current += ai_add
        
    conn.close()
    return yt_current, ai_current

def reset_ai_quota():
    """AI 할당량 관리자 리셋"""
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute("UPDATE api_usage SET ai_count = 0 WHERE id=1")
    conn.commit()
    conn.close()

def send_custom_mail(receiver_email, subject, body, channel_name, sender_name, image_file=None):
    if not receiver_email or "@" not in receiver_email: return False, "유효하지 않은 이메일"
    
    # 1. 메일 컨테이너 생성 (첨부파일 가능하도록 MIMEMultipart 사용)
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{EMAIL_USER}>"
    msg['To'] = receiver_email
    msg['Reply-To'] = "partner@glowuprizz.com"

    # 2. 이미지 처리 로직
    html_body = body
    if image_file is not None:
        # 본문 끝에 이미지 태그 추가 (cid:business_card는 아래에서 정의한 ID)
        html_body += '<br><br><img src="cid:business_card" alt="명함" style="max-width: 500px;">'

    # 3. HTML 본문 부착
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(html_body, 'html', 'utf-8'))

    # 4. 이미지 파일 데이터 부착 (Inline 방식)
    if image_file is not None:
        try:
            # Streamlit 업로드 파일에서 바이트 데이터 읽기
            img_data = image_file.getvalue()
            image = MIMEImage(img_data)
            
            # 헤더 설정 
            image.add_header('Content-ID', '<business_card>')
            image.add_header('Content-Disposition', 'inline', filename='business_card.png')
            msg.attach(image)
        except Exception as e:
            return False, f"이미지 첨부 중 오류: {str(e)}"

    # 5. 발송
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PW)
            server.sendmail(EMAIL_USER, receiver_email, msg.as_string())
        save_log(channel_name, receiver_email, "성공")
        return True, "성공"
    except Exception as e:
        save_log(channel_name, receiver_email, f"실패: {str(e)}")
        return False, str(e)

def save_log(name, email, status):
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute("INSERT INTO send_log VALUES (?, ?, ?, ?)", (name, email, status, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit(); conn.close()

def extract_exclude_list(file):
    try:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        return set(df.iloc[:,0].astype(str).str.strip().tolist())
    except: return set()

def extract_email_ai(desc):
    if not desc or len(desc) < 5: return "None"
    try:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
        if emails: return emails[0]
        # AI 호출 시 카운트
        manage_api_quota(ai_add=1)
        response = model.generate_content(f"다음 텍스트에서 이메일 주소만 추출해. 없으면 None: {desc}")
        res = response.text.strip()
        return res if "@" in res else "None"
    except: return "None"

def check_performance(up_id, subs):
    try:
        # 리스트 조회 (API 1회)
        manage_api_quota(yt_add=1)
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=10).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        if not v_ids: return False, 0, 0
        
        # 상세 조회 (API 1회)
        manage_api_quota(yt_add=1)
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs if subs > 0 else 0
        return True, avg_v, eff
    except: return False, 0, 0

def get_recent_ad_videos_ai(up_id, count):
    try:
        # API 사용 카운트 (리스트 + 상세)
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
                "링크": f"https://youtu.be/{v['id']}" # 이 링크도 나중에 LinkColumn으로 처리
            }

            if any(p in title for p in patterns) or any(p in desc for p in patterns):
                ad_indices.append(idx)
            all_videos.append(vid_data)
            
        remaining = [i for i in range(len(all_videos)) if i not in ad_indices]
        if remaining:
            prompt = "".join([f"[{i}] 제목:{all_videos[i]['영상 제목']} / 설명:{v_res['items'][i]['snippet']['description'][:300]}\n" for i in remaining])
            try:
                manage_api_quota(ai_add=1) # AI 호출 카운트
                resp = model.generate_content(f"광고/협업이 의심되는 번호만 쉼표로 출력:\n{prompt}")
                ad_indices.extend([int(x) for x in re.findall(r'\d+', resp.text)])
            except: pass
            
        final_ads = [all_videos[i] for i in sorted(list(set(ad_indices))) if i < len(all_videos)]
        return pd.DataFrame(final_ads)
    except: return pd.DataFrame()

# --- [5. 사이드바: 통합 리소스 모니터링] ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    
    # DB에서 실시간 사용량 조회 (리셋 로직 포함)
    yt_used, ai_used = manage_api_quota()
    
    st.markdown("### 📊 팀 전체 리소스 현황")
    # YouTube 할당량 500,000으로 설정
    yt_limit = 500000 
    yt_ratio = min(yt_used / yt_limit, 1.0)
    st.progress(yt_ratio)
    st.caption(f"📺 YouTube API: {yt_used:,} / {yt_limit:,} (오늘 5PM 리셋)")
    
    if yt_ratio > 0.9: st.error("⚠️ 유튜브 할당량 부족!")
    
    st.markdown("---")
    # AI 호출 횟수 표시
    st.write(f"🤖 **AI API 호출 횟수:** {ai_used:,}회")
    
    st.markdown("---")
    admin_pw = st.text_input("🔓 관리자 모드", type="password")
    if admin_pw == "rizz1000":
        st.success("Admin Access")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("AI 카운트 리셋"):
                reset_ai_quota()
                st.rerun()
        with c2:
            st.link_button("결제 관리", "https://aistudio.google.com/plan")
            
        if st.checkbox("발송 로그 보기"):
            try:
                conn = sqlite3.connect('mail_log.db')
                log_df = pd.read_sql_query("SELECT * FROM send_log ORDER BY sent_at DESC", conn)
                st.dataframe(log_df, use_container_width=True)
                conn.close()
            except: st.write("기록 없음")

# --- [6. 메인 검색 UI] ---
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
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
    # 검색 시 대략적 할당량 추가 (검색 1회당 약 100 소모 가정)
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
                
                # 채널 정보 조회 (API 사용은 check_performance 내부에서 카운트됨)
                ch_res = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=cid).execute()
                if not ch_res['items']: continue
                ch = ch_res['items'][0]
                
                title = ch['snippet']['title']
                url = f"https://youtube.com/channel/{cid}"
                if title in exclude_data or url in exclude_data: continue
                
                subs = int(ch['statistics'].get('subscriberCount', 0))
                if not (min_subs <= subs <= max_subs): continue
                
                upid = ch['contentDetails']['relatedPlaylists']['uploads']
                is_ok, avg_v, eff = check_performance(upid, subs)
                
                if is_ok and eff >= eff_target:
                    email = extract_email_ai(ch['snippet']['description'])
                    final_list.append({
                        "채널명": title,
                        "구독자": subs,
                        "평균 조회수": int(avg_v),
                        "효율": f"{eff*100:.1f}%",
                        "이메일": email,
                        "프로필": ch['snippet']['thumbnails']['default']['url'],
                        "URL": url, # 바로가기용 URL
                        "upload_id": upid
                    })
        except: break
            
    st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 및 섭외 UI] ---
if "search_results" in st.session_state and st.session_state.search_results is not None:
    st.subheader("📊 분석 결과 리스트")
    
    # URL을 클릭 가능한 링크로 표시 (LinkColumn 사용)
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "프로필": st.column_config.ImageColumn(),
            "URL": st.column_config.LinkColumn("채널 바로가기", display_text="이동"), # 바로가기 링크
            "upload_id": None
        },
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    if event.selection.rows:
        row = st.session_state.search_results.iloc[event.selection.rows[0]]
        st.divider()
        
        # [A] 딥리서치
        st.subheader(f"🔍 '{row['채널명']}' 딥리서치")
        if st.button("광고 이력 분석 시작"):
            with st.spinner("분석 중..."):
                df = get_recent_ad_videos_ai(row['upload_id'], 20)
                if not df.empty:
                    st.error(f"🚨 광고 의심 영상 {len(df)}개 발견")
                    # [변경] 영상 링크를 클릭 가능한 바로가기로 표시
                    st.dataframe(
                        df, 
                        column_config={
                            "링크": st.column_config.LinkColumn("영상 바로가기", display_text="시청")
                        },
                        use_container_width=True
                    )
                else:
                    st.success("✅ 최근 1년 내 광고 이력 없음")
            
        st.divider()
        
        # [B] 이메일 발송
        st.subheader("📧 섭외 제안서 작성")
        
        col1, col2, col3 = st.columns(3)
        with col1: sender = st.text_input("마케터 이름", value="김민준")
        with col2: email_to = st.text_input("수신 이메일", value=row['이메일'])
        with col3: st.text_input("회신 주소", value="partner@glowuprizz.com", disabled=True)
        
        tpl_key = st.selectbox("템플릿 선택", list(TEMPLATES.keys()))
        tpl = TEMPLATES[tpl_key]
        
        # 템플릿 치환
        def_sub = tpl['title'].format(name=row['채널명'], sender=sender)
        def_body = tpl['body'].format(name=row['채널명'], sender=sender)
        
        # 편집기 (HTML 태그가 포함된 상태로 보임)
        sub_final = st.text_input("제목", value=def_sub)
        body_final = st.text_area("본문 (HTML 편집 가능: <b>, <a href> 사용)", value=def_body, height=400)

        # ... (이전 코드: 템플릿 선택 및 제목/본문 편집기 부분) ...
        
        st.markdown("---")
        st.write("🖼️ **명함 이미지 첨부 (선택)**")
        uploaded_card = st.file_uploader("명함 파일 업로드 (JPG, PNG)", type=['png', 'jpg', 'jpeg'])

        # [추가] 이메일 미리보기 (이미지 포함 안내)
        with st.expander("👀 발송될 이메일 미리보기 (수신자 화면)", expanded=True):
            st.markdown(f"**받는 사람:** {email_to}")
            st.markdown(f"**제목:** {sub_final}")
            st.markdown("---")
            st.markdown(body_final, unsafe_allow_html=True)
            if uploaded_card:
                st.info("✅ 명함 이미지가 본문 하단에 포함되어 발송됩니다.")
            st.markdown("---")
            
        if st.button("🚀 이메일 전송"):
            if "@" not in email_to:
                st.error("이메일 주소를 확인해주세요.")
            else:
                with st.spinner("전송 중..."):
                    # [수정] 함수 호출 시 uploaded_card를 인자로 추가!
                    ok, msg = send_custom_mail(email_to, sub_final, body_final, row['채널명'], sender, uploaded_card)
                    
                    if ok: st.success("전송 완료!")
                    else: st.error(f"전송 실패: {msg}")
