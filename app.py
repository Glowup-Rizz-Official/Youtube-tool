import streamlit as st
import pandas as pd
import re
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
        "title": "[Glowup Rizz] 아정당 광고 협업의 건 - {name}님 제안드립니다.",
        "body": """안녕하세요, {name}님! 
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.

평소 {name}님 채널의 유익한 컨텐츠 모두 즐겨보고 있습니다!
다름이 아니라 이번에 아래 브랜드를 제안 드리고자 연락 드렸습니다.
_________________________________________________________________
제안드리는 광고 [아정당] 광고입니다.
아정당은 인터넷, 정수기, 휴대폰, TV 등 가전제품을 교체하면
최대 128만원의 지원금 혜택을 받을 수 있는 홈서비스 플랫폼입니다.

원빈님께서 광고모델로 운영되고 있으며 많은 크리에이터분들과 협업을 진행 중인 브랜드입니다.

다만 해당 광고의 경우 경험의 의한 자연스러운 소구를 원칙으로 하고 있어
직접 휴대폰, 인터넷, TV, 정수기 중 한 품목을 교체 가능한지 문의 드립니다.
(해당 과정에서 발생하는 비용은 모두 저희가 부담 할 예정입니다.)
_________________________________________________________________
협업 가능성을 논의하고자, 광고 단가에 대해 아래와 같이 문의하고자 합니다.

① 브랜디드 광고
② PPL
③ 릴스/쇼츠 광고
④ 진행 가능한 날짜

관련하여 문의사항이 있으시다면 편하게 말씀 부탁드립니다.

감사합니다.
{sender} 드림"""
    },
    "템플릿 2 (휙/보바 협업 제안)": {
        "title": "[Glowup Rizz] 휙, 보바 광고 협업의 건 - {name}님 제안드립니다.",
        "body": """안녕하세요, {name} 계정 담당자님!
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.

평소 {name} 프로필의 다양한 콘텐츠 모두 즐겨보고 있습니다!
다름이 아니라 이번에 아래 두 브랜드 광고를 제안 드리고자 연락 드렸습니다.
* 아래 제품들 이외에 내부에 다른 제품도 많으니, 궁금하신 사항이 있으시다면 언제든 편하게 연락주세요!

1. 대한민국 보조배터리 1위 브랜드 <보바>
- 동급 대비 가장 가벼운 보조배터리, 언제 어디서나 부담 없이 휴대 가능
- 대형 유튜버들이 직접 사용하고 추천하는 믿을 수 있는 제품!
- 아이디어: 일상, 여행 vlog 콘텐츠로 이동 중 제품 사용 및 데일리 필수템 소개

2. 고속 헤어 스타일러 <휙>
- 다ㅇ슨, 샤ㅇ 등 고급 스타일러와 동급 성능임에도 10만원 초반대 가성비
- 헤어디바이스 최초 임상까지 완료된 믿을 수 있는 제품
- 아이디어: 모닝/나이트 루틴, 뷰티 콘텐츠로 스타일링 추천
_________________________________________________________________
<제안>
1. 광고비 형태
2. 광고비+RS 방식 (수수료 방식으로 더 많은 수익 창출 가능)
_________________________________________________________________
협업 가능성을 논의하고자, 광고 단가에 대해 아래와 같이 문의하고자 합니다.

① 브랜디드 광고
② PPL
③ 릴스/쇼츠 광고
④ RS 진행 여부
⑤ 진행 가능한 날짜

제품을 먼저 보내드릴 수도 있으니 편하게 말씀 부탁드립니다.
궁금하신 사항은 편하게 해당 연락처로 연락 부탁드립니다.

감사합니다.
{sender} 드림."""
    }
}

# --- [3. 세션 및 DB 초기화] ---
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

if "search_results" not in st.session_state: st.session_state.search_results = None
if "quota_used" not in st.session_state: st.session_state.quota_used = 0

def init_db():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS send_log (channel_name TEXT, email TEXT, status TEXT, sent_at TEXT)')
    conn.commit(); conn.close()
init_db()

# --- [4. 핵심 로직 함수들] ---

def send_custom_mail(receiver_email, subject, body, channel_name, sender_name):
    if not receiver_email or "@" not in receiver_email: return False, "유효하지 않은 이메일"
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{EMAIL_USER}>"
    msg['To'] = receiver_email
    msg['Reply-To'] = "partner@glowuprizz.com"
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
        response = model.generate_content(f"다음 텍스트에서 이메일 주소만 추출해. 없으면 None: {desc}")
        res = response.text.strip()
        return res if "@" in res else "None"
    except: return "None"

def check_performance(up_id, subs):
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=10).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        if not v_ids: return False, 0, 0
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs if subs > 0 else 0
        return True, avg_v, eff
    except: return False, 0, 0

# --- [딥리서치 로직] ---
def get_recent_ad_videos_ai(up_id, count):
    try:
        # 1. 영상 데이터 수집
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        
        # snippet(제목,설명,날짜) + statistics(조회수) 한번에 조회
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        all_videos = []
        ad_indices = []
        
        # 1차 필터링 키워드 (제목 및 설명 전체 스캔용)
        patterns = ["유료 광고", "협찬", "광고", "AD", "Paid", "제작 지원", "제품 제공", "서포터즈"]
        
        for idx, v in enumerate(v_res.get('items', [])):
            title = v['snippet']['title']
            desc = v['snippet'].get('description', '') # 설명 전체 가져오기
            pub_date_str = v['snippet']['publishedAt']
            pub_date = datetime.strptime(pub_date_str, '%Y-%m-%dT%H:%M:%SZ')
            
            # [날짜 필터링] 1년(365일) 지난 영상은 제외
            if (datetime.now() - pub_date).days > 365:
                continue

            vid_data = {
                "영상 제목": title,
                "업로드": pub_date_str[:10],
                "조회수": int(v['statistics'].get('viewCount', 0)),
                "링크": f"https://youtu.be/{v['id']}"
            }
            
            # [1단계] Python 키워드 검사 (제목 + 설명 전체)
            # 설명란에 숨겨진 광고 표기를 찾기 위해 desc 전체를 검사합니다.
            if any(p in title for p in patterns) or any(p in desc for p in patterns):
                ad_indices.append(idx)
            
            all_videos.append(vid_data)
            
        # [2단계] AI 정밀 분석 (1차에서 안 걸린 영상들 대상)
        remaining = [i for i in range(len(all_videos)) if i not in ad_indices]
        
        if remaining:
            # AI에게는 토큰 절약을 위해 '제목' + '설명 앞부분 500자'만 보냅니다.
            # 설명 전체를 보내면 너무 길어서 에러가 날 수 있습니다. 보통 광고 고지는 앞부분이나 끝부분에 있습니다.
            prompt_text = ""
            for i in remaining:
                # 줄바꿈 제거하여 한 줄로 만듦
                clean_desc = all_videos[i].get('desc_snippet', '').replace('\n', ' ') 
                # AI 프롬프트 구성: 인덱스 | 제목 | 설명(앞 500자)
                prompt_text += f"[{i}] 제목: {all_videos[i]['영상 제목']} / 설명 일부: {v_res['items'][i]['snippet']['description'][:500]}\n"
            
            try:
                resp = model.generate_content(
                    f"다음 영상들의 제목과 설명 일부를 보고, '제품 리뷰', '단순 선물', '숙제', '홍보' 성격이 강한 영상의 번호만 쉼표로 나열해줘. 없으면 None:\n\n{prompt_text}"
                )
                ai_idx = [int(x) for x in re.findall(r'\d+', resp.text)]
                ad_indices.extend(ai_idx)
            except: pass
            
        # 중복 제거 및 인덱스 정렬하여 결과 반환
        final_ads = [all_videos[i] for i in sorted(list(set(ad_indices))) if i < len(all_videos)]
        return pd.DataFrame(final_ads)
        
    except Exception as e:
        # 에러 발생 시 빈 데이터프레임 반환 (프로그램 멈춤 방지)
        return pd.DataFrame()

# --- [5. 사이드바: 관리자 및 할당량 모니터링] ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    
    st.markdown("### 📊 API 리소스 현황")
    quota_ratio = min(st.session_state.quota_used / 10000, 1.0)
    st.progress(quota_ratio)
    st.caption(f"YouTube Quota: {st.session_state.quota_used} / 10,000")
    if quota_ratio > 0.9: st.warning("⚠️ 할당량 주의!")

    st.markdown("---")
    admin_pw = st.text_input("🔓 관리자 모드", type="password")
    
    if admin_pw == "rizz1000":
        st.success("관리자 승인")
        if st.button("🔄 할당량 리셋"):
            st.session_state.quota_used = 0
            st.rerun()
        st.link_button("💳 AI 토큰 관리", "https://aistudio.google.com/plan")
        st.markdown("---")
        if st.checkbox("📋 메일 발송 로그 보기"):
            try:
                conn = sqlite3.connect('mail_log.db')
                log_df = pd.read_sql_query("SELECT * FROM send_log ORDER BY sent_at DESC", conn)
                st.dataframe(log_df, use_container_width=True)
                conn.close()
            except: st.write("기록 없음")

# --- [6. 메인 검색 화면] ---
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
with st.form("search_form"):
    exclude_file = st.file_uploader("제외할 채널 리스트(엑셀/CSV)", type=['xlsx', 'csv'])
    keywords_input = st.text_input("🔎 검색 키워드 (쉼표 구분)", placeholder="먹방, 일상 브이로그")
    
    c1, c2, c3 = st.columns(3)
    with c1: selected_country = st.selectbox("국가", list(COUNTRIES.keys()))
    with c2: 
        sub_range = st.selectbox("구독자 범위", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[sub_range]
    with c3: max_res = st.number_input("분석 샘플 수", 5, 50, 20)
    
    c4, c5 = st.columns(2)
    with c4: search_mode = st.radio("검색 방식", ["영상 기반 (추천)", "채널명 기반"], horizontal=True)
    with c5: eff_target = st.slider("최소 조회수 효율 (%)", 0, 100, 30) / 100
    
    submit_button = st.form_submit_button("🚀 분석 시작")

if submit_button and keywords_input:
    st.session_state.quota_used += 100
    exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
    kws = [k.strip() for k in keywords_input.split(",")]
    
    final_list = []
    processed = set()
    prog = st.progress(0)
    total_steps = len(kws) * max_res
    curr_step = 0
    
    for kw in kws:
        try:
            if "영상" in search_mode:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="video", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
            else:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
            
            for item in search['items']:
                curr_step += 1
                prog.progress(min(curr_step/total_steps, 1.0))
                cid = item['snippet']['channelId']
                if cid in processed: continue
                processed.add(cid)
                
                ch_res = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=cid).execute()
                if not ch_res['items']: continue
                ch = ch_res['items'][0]
                
                title = ch['snippet']['title']
                if title in exclude_data: continue
                
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
                        "upload_id": upid
                    })
        except: break
            
    st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 및 섭외 통합 화면] ---
if st.session_state.search_results is not None and not st.session_state.search_results.empty:
    st.subheader("📊 분석 결과 리스트")
    event = st.dataframe(st.session_state.search_results, column_config={"프로필": st.column_config.ImageColumn(), "upload_id": None}, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    if event.selection.rows:
        idx = event.selection.rows[0]
        row = st.session_state.search_results.iloc[idx]
        
        st.divider()
        # 딥리서치 (제목+설명+AI 하이브리드)
        st.subheader(f"🔍 '{row['채널명']}' 광고 이력 딥리서치")
        an_cnt = st.selectbox("최근 영상 분석 개수", [10, 20, 30], index=1)
        
        with st.spinner("최근 1년치 영상의 제목과 설명란을 정밀 분석 중입니다..."):
            ad_df = get_recent_ad_videos_ai(row['upload_id'], an_cnt)
            if not ad_df.empty:
                st.error(f"🚨 광고/협업 의심 영상 {len(ad_df)}개 감지됨")
                st.dataframe(ad_df, use_container_width=True)
            else:
                st.success("✅ 최근 1년 내 광고 이력이 감지되지 않았습니다.")

        st.divider()
        # 섭외 메일
        st.subheader(f"📧 '{row['채널명']}' 섭외 제안서 발송")
        col1, col2, col3 = st.columns(3)
        with col1: sender_name = st.text_input("마케터 이름", value="김민준")
        with col2: target_email = st.text_input("수신 이메일", value=row['이메일'])
        with col3: st.text_input("회신 주소", value="partner@glowuprizz.com", disabled=True)
            
        tpl_choice = st.selectbox("제안 템플릿", list(TEMPLATES.keys()))
        sel_tpl = TEMPLATES[tpl_choice]
        final_sub = sel_tpl['title'].format(name=row['채널명'], sender=sender_name)
        final_body = sel_tpl['body'].format(name=row['채널명'], sender=sender_name)
        
        edit_sub = st.text_input("제목 수정", value=final_sub)
        edit_body = st.text_area("본문 수정", value=final_body, height=350)
        
        if st.button(f"🚀 {tpl_choice} 전송"):
            if "@" not in target_email or len(target_email) < 5:
                st.error("이메일 오류")
            else:
                with st.spinner("전송 중..."):
                    is_sent, log_msg = send_custom_mail(target_email, edit_sub, edit_body, row['채널명'], sender_name)
                    if is_sent: st.success("✅ 전송 완료!")
                    else: st.error(f"❌ 실패: {log_msg}")

elif st.session_state.search_results is not None:
    st.warning("조건에 맞는 채널이 없습니다.")
