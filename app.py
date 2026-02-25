import streamlit as st
import pandas as pd
import sqlite3
import requests
import re
import time
import os
import random
import base64
import shutil
import platform
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.header import Header

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

import googleapiclient.discovery
import google.generativeai as genai

# ==========================================
# ⚙️ 기본 설정 및 공통 초기화
# ==========================================
st.set_page_config(page_title="Glowup Rizz 통합 솔루션", page_icon="💡", layout="wide")

# API Key 설정
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# ==========================================
# 🗄️ 데이터베이스 설정 (크리에이터용 SQLite / 브랜드용 CSV)
# ==========================================
def init_creator_db():
    conn = sqlite3.connect('influencer_db.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS influencers 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, category TEXT, channel_name TEXT, email TEXT, url TEXT, subscribers INTEGER, description TEXT, collected_at TEXT)''')
    try:
        c.execute("ALTER TABLE influencers ADD COLUMN status TEXT DEFAULT '대기'")
    except sqlite3.OperationalError:
        pass
        
    c.execute('''CREATE TABLE IF NOT EXISTS api_usage 
                 (id INTEGER PRIMARY KEY, youtube_count INTEGER, ai_count INTEGER, last_reset TEXT)''')
    c.execute("SELECT count(*) FROM api_usage")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO api_usage (id, youtube_count, ai_count, last_reset) VALUES (1, 0, 0, ?)", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    conn.commit()
    conn.close()

def save_creator_to_db(platform, category, channel_name, email, url, subscribers, description):
    conn = sqlite3.connect('influencer_db.db')
    c = conn.cursor()
    c.execute("SELECT id FROM influencers WHERE url=?", (url,))
    if not c.fetchone():
        c.execute("INSERT INTO influencers (platform, category, channel_name, email, url, subscribers, description, collected_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '대기')",
                  (platform, category, channel_name, email, url, subscribers, description, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    conn.close()

def update_creator_status(email, status):
    conn = sqlite3.connect('influencer_db.db')
    c = conn.cursor()
    c.execute("UPDATE influencers SET status = ? WHERE email = ?", (status, email))
    conn.commit()
    conn.close()

BRAND_DB_FILE = "glowup_crm_db.csv"
if not os.path.exists(BRAND_DB_FILE):
    pd.DataFrame(columns=["Email", "Keyword", "Discovered_Date", "Last_Sent_Date", "Send_Count", "Template_Used"]).to_csv(BRAND_DB_FILE, index=False, encoding="utf-8-sig")

def load_brand_db():
    try: return pd.read_csv(BRAND_DB_FILE, encoding='utf-8-sig')
    except: return pd.read_csv(BRAND_DB_FILE, encoding='cp949')

def save_brand_db(df):
    df.to_csv(BRAND_DB_FILE, index=False, encoding="utf-8-sig")

init_creator_db()

# ==========================================
# 🛠️ 공통 / 유틸리티 함수
# ==========================================
def get_kst_now(): return datetime.now(timezone.utc) + timedelta(hours=9)

def manage_api_quota(yt_add=0, ai_add=0):
    conn = sqlite3.connect('influencer_db.db')
    c = conn.cursor()
    c.execute("SELECT youtube_count, ai_count, last_reset FROM api_usage WHERE id=1")
    yt_current, ai_current, last_reset_str = c.fetchone()
    now_kst = get_kst_now()
    last_reset_kst = datetime.strptime(last_reset_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=9))) if last_reset_str else now_kst
    today_5pm = now_kst.replace(hour=17, minute=0, second=0, microsecond=0)
    reset_threshold = today_5pm - timedelta(days=1) if now_kst < today_5pm else today_5pm
    if last_reset_kst < reset_threshold:
        yt_current = 0
        c.execute("UPDATE api_usage SET youtube_count = 0, last_reset = ? WHERE id=1", (now_kst.strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
    if yt_add > 0 or ai_add > 0:
        c.execute("UPDATE api_usage SET youtube_count = youtube_count + ?, ai_count = ai_count + ? WHERE id=1", (yt_add, ai_add))
        conn.commit()
        yt_current += yt_add; ai_current += ai_add
    conn.close()
    return yt_current, ai_current

def get_image_base64(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode('utf-8')
    return None

# ==========================================
# 🚀 메인 네비게이션 (사이드바)
# ==========================================
with st.sidebar:
    st.image("https://via.placeholder.com/300x100.png?text=Glowup+Rizz", use_container_width=True)
    st.markdown("### 🎛️ 솔루션 모드 선택")
    app_mode = st.radio("작업 영역을 선택하세요", ["1️⃣ 크리에이터 발굴 엔진 (시딩용)", "2️⃣ 브랜드 영업 자동화 (B2B 제안용)"])
    st.markdown("---")
    
    yt_used, ai_used = manage_api_quota()
    st.markdown("### 📊 리소스 현황")
    st.progress(min(yt_used / 500000, 1.0))
    st.caption(f"📺 YouTube API: {yt_used:,} / 500,000")
    st.write(f"🤖 **AI API 호출 횟수:** {ai_used:,}회")

# ==========================================
# 🟢 MODE 1: 크리에이터 발굴 엔진 & 시딩 자동화
# ==========================================
if "1️⃣" in app_mode:
    st.title("🌐 Glowup Rizz 크리에이터 검색 엔진 & 시딩 자동화")
    
    # [시딩용 고정 발신자]
    FIXED_SENDER_NAME = "박혜란"
    FIXED_CARD_PATH = "cards/HR.png"
    
    COUNTRIES = {"대한민국": "KR", "미국": "US", "일본": "JP"}
    SUB_RANGES = {"전체": (0, 100000000), "1만 미만": (0, 10000), "1만 ~ 5만": (10000, 50000), "5만 ~ 10만": (50000, 100000), "10만 ~ 50만": (100000, 500000), "50만 ~ 100만": (500000, 1000000)}
    CATEGORIES = ["뷰티", "패션", "리빙", "육아", "반려동물", "IT/테크", "먹방/푸드", "기타"]

    if "youtube_results" not in st.session_state: st.session_state.youtube_results = None

    def extract_email_ai(desc):
        if not desc or len(desc) < 5: return ""
        try:
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
            if emails: return emails[0]
            manage_api_quota(ai_add=1)
            response = model.generate_content(f"다음 텍스트에서 이메일 주소만 추출해. 없으면 None: {desc}")
            res = response.text.strip()
            return res if "@" in res else ""
        except: return ""

    def check_performance(up_id, subs):
        try:
            manage_api_quota(yt_add=1)
            req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=10).execute()
            v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
            if not v_ids: return False, 0, 0
            manage_api_quota(yt_add=1)
            v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
            longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']]
            if not longforms: return False, 0, 0
            avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
            eff = avg_v / subs if subs > 0 else 0
            return True, avg_v, eff
        except: return False, 0, 0

    def scrape_sns_influencers(platform, keyword, category, max_pages=3):
        influencers = []
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        site_domain = "instagram.com" if platform == "Instagram" else "tiktok.com"
        search_query = f"site:{site_domain} {keyword} \"@\""
        if platform == "Instagram": search_query += " -\"/p/\" -\"/reels/\" -\"/tags/\""
        else: search_query += " -\"/video/\""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        
        prog = st.progress(0)
        for page in range(max_pages):
            prog.progress((page + 1) / max_pages)
            url = f"https://www.google.com/search?q={search_query}&start={page*10}"
            try:
                response = requests.get(url, headers=headers)
                soup = BeautifulSoup(response.text, 'html.parser')
                for g in soup.find_all('div', class_='g'):
                    link_tag = g.find('a')
                    snippet_tag = g.find('div', class_='VwiC3b') 
                    if link_tag and snippet_tag:
                        link = link_tag['href']
                        snippet = snippet_tag.text
                        emails = re.findall(email_pattern, snippet)
                        if emails and site_domain in link:
                            channel_name = link.split(f"{site_domain}/")[-1].replace("/", "").replace("@", "")
                            influencers.append({"플랫폼": platform, "카테고리": category, "채널명": channel_name, "이메일": emails[0], "URL": link, "소개글": snippet})
                time.sleep(2)
            except Exception as e: break
        return pd.DataFrame(influencers).drop_duplicates(subset=['이메일'])

    tab_yt, tab_ig, tab_tk, tab_mail, tab_db = st.tabs(["📺 YouTube 검색", "📸 Instagram 검색", "🎵 TikTok 검색", "💌 시딩 메일 발송", "🗄️ 플랫폼별 DB 관리"])

    with tab_yt:
        st.subheader("유튜브 크리에이터 딥서치")
        with st.form("yt_search"):
            kws = st.text_input("검색 키워드 (쉼표 구분)")
            category_yt = st.selectbox("저장할 카테고리 지정", CATEGORIES)
            c1, c2, c3 = st.columns(3)
            with c1: selected_country = st.selectbox("국가", list(COUNTRIES.keys()))
            with c2: 
                sub_range = st.selectbox("구독자 범위", list(SUB_RANGES.keys()))
                min_subs, max_subs = SUB_RANGES[sub_range]
            with c3: max_res = st.number_input("분석 샘플 수", 5, 50, 20)
            c4, c5 = st.columns(2)
            with c4: search_mode = st.radio("검색 방식", ["영상 기반", "채널명 기반"], horizontal=True)
            with c5: eff_target = st.slider("최소 효율 (%)", 0, 100, 30) / 100
            btn_yt = st.form_submit_button("🚀 유튜브 분석 시작")

        if btn_yt and kws:
            manage_api_quota(yt_add=100)
            keywords = [k.strip() for k in kws.split(",")]
            final_list, processed = [], set()
            prog, curr, total = st.progress(0), 0, len(keywords) * max_res
            for kw in keywords:
                try:
                    search_type = "video" if "영상" in search_mode else "channel"
                    search = YOUTUBE.search().list(q=kw, part="snippet", type=search_type, maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                    for item in search['items']:
                        curr += 1; prog.progress(min(curr/total, 1.0))
                        cid = item['snippet']['channelId']
                        if cid in processed: continue
                        processed.add(cid)
                        ch_res = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=cid).execute()
                        if not ch_res['items']: continue
                        ch = ch_res['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        if not (min_subs <= subs <= max_subs): continue
                        upid = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(upid, subs)
                        if is_ok and eff >= eff_target:
                            email = extract_email_ai(ch['snippet']['description'])
                            final_list.append({"채널명": ch['snippet']['title'], "구독자": subs, "평균 조회수": int(avg_v), "효율": f"{eff*100:.1f}%", "이메일": email, "프로필": ch['snippet']['thumbnails']['default']['url'], "URL": f"https://youtube.com/channel/{cid}", "소개글": ch['snippet']['description']})
                except: break
            st.session_state.youtube_results = pd.DataFrame(final_list)

        if st.session_state.youtube_results is not None and not st.session_state.youtube_results.empty:
            st.dataframe(st.session_state.youtube_results, column_config={"프로필": st.column_config.ImageColumn(), "URL": st.column_config.LinkColumn("이동")}, use_container_width=True)
            if st.button("💾 검색 결과를 DB에 저장", key="save_yt"):
                saved_count = 0
                for _, row in st.session_state.youtube_results.iterrows():
                    if row['이메일']:
                        save_creator_to_db("YouTube", category_yt, row['채널명'], row['이메일'], row['URL'], row['구독자'], row['소개글'])
                        saved_count += 1
                st.success(f"{saved_count}명의 크리에이터가 DB에 저장되었습니다!")

    with tab_ig:
        st.subheader("인스타그램 인플루언서 발굴 (Bio 스크래핑)")
        with st.form("ig_search"):
            kw_ig = st.text_input("검색 키워드 (예: 뷰티케어, 협찬환영)")
            cat_ig = st.selectbox("분류 카테고리", CATEGORIES)
            pages_ig = st.slider("검색 깊이 (페이지 수)", 1, 10, 3)
            if st.form_submit_button("🚀 인스타 검색 시작") and kw_ig:
                df_ig = scrape_sns_influencers("Instagram", kw_ig, cat_ig, pages_ig)
                if not df_ig.empty:
                    st.success(f"이메일이 포함된 {len(df_ig)}개의 계정을 찾았습니다.")
                    st.dataframe(df_ig, column_config={"URL": st.column_config.LinkColumn("이동")}, use_container_width=True)
                    for _, row in df_ig.iterrows(): save_creator_to_db(row['플랫폼'], row['카테고리'], row['채널명'], row['이메일'], row['URL'], 0, row['소개글'])

    with tab_tk:
        st.subheader("틱톡 크리에이터 발굴 (Bio 스크래핑)")
        with st.form("tk_search"):
            kw_tk = st.text_input("검색 키워드 (예: 메이크업, 비즈니스)")
            cat_tk = st.selectbox("분류 카테고리", CATEGORIES)
            pages_tk = st.slider("검색 깊이 (페이지 수)", 1, 10, 3)
            if st.form_submit_button("🚀 틱톡 검색 시작") and kw_tk:
                df_tk = scrape_sns_influencers("TikTok", kw_tk, cat_tk, pages_tk)
                if not df_tk.empty:
                    st.success(f"이메일이 포함된 {len(df_tk)}개의 계정을 찾았습니다.")
                    st.dataframe(df_tk, column_config={"URL": st.column_config.LinkColumn("이동")}, use_container_width=True)
                    for _, row in df_tk.iterrows(): save_creator_to_db(row['플랫폼'], row['카테고리'], row['채널명'], row['이메일'], row['URL'], 0, row['소개글'])

    with tab_mail:
        st.subheader("💌 크리에이터 시딩 제안 메일 발송")
        
        conn = sqlite3.connect('influencer_db.db')
        df_pending = pd.read_sql_query("SELECT id, platform, category, channel_name, email FROM influencers WHERE status='대기'", conn)
        conn.close()
        
        st.info(f"발송 대기 중인 크리에이터가 총 **{len(df_pending)}명** 있습니다.")
        
        col_t1, col_t2 = st.columns(2)
        with col_t1: template_choice = st.radio("시딩 템플릿 선택", ["1. MELV (립시럽/립타투)", "2. SOLV (모델링팩)"])
        with col_t2: 
            st.write(f"🪪 **고정 발신자:** {FIXED_SENDER_NAME}")
            st.write(f"🪪 **첨부 명함:** `{FIXED_CARD_PATH}`")
            
        c1, c2 = st.columns(2)
        with c1: sender_email = st.text_input("보내는 사람 구글 이메일", value="rizzsender@gmail.com")
        with c2: sender_pw = st.text_input("구글 앱 비밀번호 16자리", type="password")

        selected_creators = st.multiselect("발송할 크리에이터 이메일 선택 (채널명 표시)", df_pending['email'].tolist(), format_func=lambda x: f"{df_pending[df_pending['email']==x]['channel_name'].values[0]} ({x})")

        if st.button("🚀 선택한 크리에이터에게 메일 발송", type="primary"):
            if not sender_pw: st.error("앱 비밀번호를 입력해주세요!")
            elif not selected_creators: st.warning("발송할 크리에이터를 1명 이상 선택해주세요.")
            else:
                prog_bar = st.progress(0)
                success_count = 0
                
                for idx, t_email in enumerate(selected_creators):
                    c_name = df_pending[df_pending['email']==t_email]['channel_name'].values[0]
                    
                    msg = MIMEMultipart('related')
                    msg['From'] = sender_email
                    msg['To'] = t_email
                    
                    if "MELV" in template_choice:
                        msg['Subject'] = Header(f"[MELV] {c_name}님, 멜브 첫 공식 런칭 제품 시딩 제안드립니다 💖", 'utf-8')
                        body = f"""<div style="font-family: 'Apple SD Gothic Neo', sans-serif; line-height: 1.6; color: #222;">
                        안녕하세요, {c_name}님!<br>
                        뷰티 브랜드 MELV(멜브) MD {FIXED_SENDER_NAME}입니다. :)<br><br>
                        이번 MELV의 첫 공식 런칭으로, 브랜드 무드와 가장 잘 어울리는 크리에이터분들께만 제일 빠르게! 런칭 제품을 선물 드리고 싶어 연락드렸습니다! 💖<br><br>
                        <b>1. MELV 립시럽 (2종)</b><br>
                        기존 글로우 립의 요플레 현상과 끈적임을 확실하게 잡았습니다.<br>
                        특히 말랑한 물방울 실리콘 팁이 맑은 광택감을 온전히 살려주며, 호호바씨오일과 시어버터를 듬뿍 담아 단순히 겉광만 내는 것이 아니라 건조한 입술에 깊은 보습감까지 꽉 채워줍니다.<br><br>
                        <b>2. MELV 립타투 (3종)</b><br>
                        촌스러운 핑크 착색이 아닌, 감성적인 뮤티드 컬러로 뽑아낸 신개념 타투 립입니다.<br>
                        밥을 먹거나 물놀이를 해도 쉽게 지워지지 않는 강력한 지속력을 자랑하며, 보습 성분(콜라겐, 펩타이드)을 함유하여 떼어낼 때 자극이 적고 건조함 없이 편안하게 마무리됩니다.<br>
                        (자연스러운 오버립 연출로 중안부 여백을 예쁘게 커버해 줍니다!)<br><br>
                        {c_name}님을 위해 아낌없이 전 컬러를 꽉 채워 보내드릴 예정입니다!<br>
                        본 키트는 제품 협찬으로, 수령 후 인스타그램 피드 또는 스토리에 공식 계정(@melv.kr) 태그와 함께 업로드가 가능하신 분들께만 한정적으로 발송해 드리고 있습니다. 🙏<br>
                        (선정된 소수의 분들께만 드리는 키트인 만큼, {c_name}님의 감각적인 후기를 꼭 보고 싶습니다...💖)<br><br>
                        진행이 가능하시다면 받아보실 <b>[성함 / 연락처 / 주소]</b>를 남겨주세요. 정성껏 포장해서 보내드리겠습니다.<br><br>
                        감사합니다!<br><br>
                        <img src="cid:biz_card" alt="{FIXED_SENDER_NAME} 명함" style="max-width: 400px; border: 1px solid #eaeaea; border-radius: 4px;">
                        </div>"""
                        attach_images = ["melv1.jpg", "melv2.jpg"]
                    else:
                        msg['Subject'] = Header(f"[SOLV] {c_name}님, 솔브 첫 공식 런칭 에스테틱 모델링팩 시딩 제안드립니다 💖", 'utf-8')
                        body = f"""<div style="font-family: 'Apple SD Gothic Neo', sans-serif; line-height: 1.6; color: #222;">
                        안녕하세요, {c_name}님!<br>
                        기초 뷰티 브랜드 SOLV(솔브) MD {FIXED_SENDER_NAME}입니다. :)<br><br>
                        이번 SOLV의 첫 공식 런칭으로, 브랜드 무드와 가장 잘 어울리는 크리에이터분들께만 제일 빠르게! 런칭 제품을 선물 드리고 싶어 연락드렸습니다! 💖<br><br>
                        <b>&lt;SOLV 모델링팩(5개입)&gt;</b><br>
                        💧 <b>물 조절 실패 ZERO!</b><br>
                        기존 모델링팩의 단점인 가루 날림과 번거로운 물 조절은 이제 그만! 베이스와 세럼을 섞기만 하면 되는 간편한 방식으로, 떼어낸 후에도 건조함 없이 피부 위 윤광 코팅 효과를 선사합니다.<br><br>
                        ❄️ <b>에스테틱 급 쿨링 효과!</b><br>
                        시중 모델링팩 중 쿨링 성분을 최대치로 담아, 열감으로 넓어진 모공과 예민해진 피부를 즉각적으로 진정시켜 에스테틱에서 관리받은 듯한 최상의 컨디션을 만들어줍니다.<br><br>
                        💄 <b>화잘먹을 위한 필수템!</b><br>
                        피부 온도가 낮아지면 베이스 메이크업의 밀착력이 달라집니다. 홈케어로 피부결을 정돈해 메이크업 시간과 화장품 비용을 획기적으로 줄여보세요.<br><br>
                        <b>[사용 방법 & TIP]</b><br>
                        팩볼에 1제+2제를 컵에 넣고 빠르게 섞어 스파출라로 펴 바른 뒤 완전히 마르면 제거해 주세요. (TIP: 가장자리는 두껍게 바르면 한 번에 깔끔하게 제거됩니다!)<br>
                        남은 영양감은 툭툭 두드려 흡수해 주세요! 별도의 세안이 필요 없는 고영양 세럼 제형입니다.<br><br>
                        본 제품은 협찬으로, 수령 후 인스타그램 피드 또는 스토리에 공식 계정(@solv.kr) 태그와 함께 업로드가 가능하신 분들께만 한정적으로 발송해 드리고 있습니다. 🙏<br>
                        (선정된 소수의 분들께만 드리는 이벤트인 만큼, {c_name}님의 감각적인 후기를 꼭 보고 싶습니다...💖)<br><br>
                        진행이 가능하시다면 받아보실 <b>[성함 / 연락처 / 주소]</b>를 남겨주세요. 정성껏 포장해서 보내드리겠습니다.<br><br>
                        감사합니다!<br><br>
                        <img src="cid:biz_card" alt="{FIXED_SENDER_NAME} 명함" style="max-width: 400px; border: 1px solid #eaeaea; border-radius: 4px;">
                        </div>"""
                        attach_images = ["solv1.jpg", "solv2.jpg"]

                    msg.attach(MIMEMultipart('alternative')).attach(MIMEText(body, 'html', 'utf-8'))
                    
                    if os.path.exists(FIXED_CARD_PATH):
                        with open(FIXED_CARD_PATH, "rb") as f:
                            img_data = MIMEImage(f.read())
                            img_data.add_header('Content-ID', '<biz_card>')
                            msg.attach(img_data)
                    
                    for img_name in attach_images:
                        if os.path.exists(img_name):
                            with open(img_name, "rb") as f:
                                part = MIMEApplication(f.read(), Name=img_name)
                                part['Content-Disposition'] = f'attachment; filename="{img_name}"'
                                msg.attach(part)

                    try:
                        server = smtplib.SMTP('smtp.gmail.com', 587)
                        server.starttls()
                        server.login(sender_email, sender_pw.replace(' ', ''))
                        server.send_message(msg)
                        server.quit()
                        
                        update_creator_status(t_email, '발송완료')
                        success_count += 1
                        time.sleep(2)
                    except Exception as e:
                        st.error(f"{t_email} 발송 실패: {e}")
                    
                    prog_bar.progress((idx + 1) / len(selected_creators))
                
                st.success(f"🎉 총 {success_count}명의 크리에이터에게 시딩 제안 메일을 성공적으로 발송했습니다!")

    with tab_db:
        st.subheader("🗄️ 수집된 크리에이터 플랫폼별 DB")
        conn = sqlite3.connect('influencer_db.db')
        df_db = pd.read_sql_query("SELECT platform, category, channel_name, email, url, collected_at, status FROM influencers ORDER BY collected_at DESC", conn)
        conn.close()

        db_yt, db_ig, db_tk = st.tabs(["📺 YouTube DB", "📸 Instagram DB", "🎵 TikTok DB"])
        
        def render_platform_db(plat_name, df_all):
            df_plat = df_all[df_all['platform'] == plat_name]
            st.write(f"총 **{len(df_plat)}**명의 {plat_name} 데이터가 있습니다.")
            st.dataframe(df_plat, column_config={"url": st.column_config.LinkColumn("링크")}, use_container_width=True, hide_index=True)
            if not df_plat.empty:
                csv = df_plat.to_csv(index=False).encode('utf-8-sig')
                st.download_button(label=f"📥 {plat_name} 목록 CSV 다운로드", data=csv, file_name=f"influencers_{plat_name}.csv", mime="text/csv")

        with db_yt: render_platform_db("YouTube", df_db)
        with db_ig: render_platform_db("Instagram", df_db)
        with db_tk: render_platform_db("TikTok", df_db)

# ==========================================
# 🔵 MODE 2: 브랜드 영업 자동화 (B2B 제안용 - 4인 선택 발송)
# ==========================================
elif "2️⃣" in app_mode:
    st.title("💡 Glowup Rizz 브랜드 영업 자동화 시스템")
    
    # [B2B 발신자 선택 목록 (박혜란 제외)]
    B2B_SENDER_INFO = {
        "윤혜선": "cards/HS.png",
        "김민준": "cards/MJ.png",
        "서영석": "cards/YS.png",
        "김효훈": "cards/HH.png"
    }

    def get_email_templates(sender_name):
        FONT_STYLE = "font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', '맑은 고딕', 'Noto Sans KR', sans-serif; font-size: 14px; line-height: 1.6; color: #222222;"
        FORM_LINK = "<div style='background-color: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #e9ecef; margin: 25px 0; text-align: center;'><p style='margin: 0 0 10px 0; font-size: 15px; font-weight: bold; color: #333;'>🚀 COSY / YOGO 상시 입점 제휴 제안서 확인 및 신청</p><a href='https://forms.gle/Dte233GXJrR7nhpJ8' target='_blank' style='display: inline-block; padding: 12px 24px; background-color: #1a73e8; color: #ffffff; text-decoration: none; font-weight: bold; border-radius: 6px; font-size: 15px;'>👉 입점 신청 폼 바로가기 (클릭)</a></div>"
        SIGNATURE_HTML = f"<p style='margin-top: 30px; margin-bottom: 20px;'>긴 글 읽어주셔서 감사합니다.<br><b>글로우업리즈 {sender_name} 드림</b></p><img src='cid:biz_card' alt='{sender_name} 명함' style='max-width: 400px; height: auto; border: 1px solid #eaeaea; border-radius: 4px; display: block;'>"
        
        return {
            "1. [필살기] 커머스(117만) + 코시/상시": {
                "subject": "[글로우업리즈] 117만 유튜버 채널 연계 - 브랜드 입점 제안의 건", 
                "body": f"<div style=\"{FONT_STYLE}\"><p>대표님, 안녕하세요.<br>크리에이터 커머스 플랫폼 <b>글로우업리즈 {sender_name}</b>입니다.</p><p>단순히 제품을 진열만 하는 일반적인 제안이 아닙니다. 저희와 함께하시면 압도적인 파이프라인을 구축하실 수 있습니다.</p>{FORM_LINK}{SIGNATURE_HTML}</div>"
            },
            "2. [코시 중심] 마케팅 예산 없는 신생 브랜드용": {
                "subject": "[글로우업리즈] 인플루언서 시딩 비용 0원 - 코시(COSY) 입점 제안의 건", 
                "body": f"<div style=\"{FONT_STYLE}\"><p>대표님, 안녕하세요.<br>크리에이터 커머스 플랫폼 <b>글로우업리즈 {sender_name}</b>입니다.</p><p>저희 플랫폼의 <b>'크리에이터 자율 매칭 시스템(COSY)'</b>을 활용하시면 섭외 고민이 단번에 해결됩니다.</p>{FORM_LINK}{SIGNATURE_HTML}</div>"
            }
        }

    tab_ai, tab_scrape, tab_mail, tab_crm = st.tabs(["🧠 AI 타겟 분석", "🕵️‍♀️ 스토어 메일 수집", "💌 콜드메일 발송", "📊 B2B CRM"])

    with tab_ai:
        st.subheader("🧠 검색 키워드 기반 발송 전략 추천")
        with st.form("ai_strategy_form"):
            ai_keyword = st.text_input("분석할 업종 키워드 (예: 색조화장품)")
            if st.form_submit_button("전략 분석하기") and ai_keyword:
                prompt = f"너는 플랫폼 '글로우업리즈'의 입점 영업을 담당해. 타겟은 '{ai_keyword}' 파는 브랜드 대표야. 그들의 페인포인트를 분석하고 추천 템플릿과 영업 팁을 줘."
                st.info(model.generate_content(prompt).text)

   
    with tab_scrape:
        st.subheader("1. 새로운 브랜드 타겟 찾기 (스마트스토어)")
        keyword = st.text_input("스마트스토어 검색 키워드 (예: 코스메틱 공식)")
        if st.button("수집 시작", type="primary"):
            if keyword:
                log_box = st.empty()
                log_box.info("크롬 브라우저를 준비 중입니다...")
                df = load_brand_db()
                existing_emails = set(df['Email'].tolist())
                new_data = []
                
                options = webdriver.ChromeOptions()
                options.add_argument('--no-sandbox') 
                options.add_argument('--disable-dev-shm-usage') 
                options.add_argument('--disable-gpu')
                
                # --- 운영체제(OS) 기반 완벽한 로컬/클라우드 분기 ---
                try:
                    if platform.system() == "Linux":
                        # ☁️ 스트림릿 클라우드 환경 (화면 숨김)
                        options.add_argument('--headless=new') 
                        options.binary_location = shutil.which("chromium") or shutil.which("chromium-browser")
                        driver = webdriver.Chrome(service=Service(shutil.which("chromedriver")), options=options)
                    else:
                        # 💻 내 컴퓨터 환경 (화면 띄움)
                        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
                except Exception as e:
                    st.error(f"🚨 브라우저 실행 실패: {e}")
                    st.stop()
                # -----------------------------------------------

                log_box.info("구글 검색을 시작합니다...")
                driver.get(f"https://www.google.com/search?q=site:smartstore.naver.com+\"{keyword}\"")
                time.sleep(3) # 🌟 페이지 로딩을 확실히 기다림 (매우 중요)
                
                page = 1
                while True:
                    log_box.info(f"[{page}페이지] 스캔 중...")
                    time.sleep(random.uniform(2, 4))
                    
                    try:
                        # 🌟 구글 봇 차단(CAPTCHA) 확인용 안전장치
                        if "sorry" in driver.current_url or "captcha" in driver.page_source.lower():
                            st.error("🚨 구글 봇 차단(CAPTCHA)에 걸렸습니다. 브라우저에서 직접 로봇이 아닙니다를 체크하거나, 잠시 후 다시 시도하세요.")
                            break

                        body_text = driver.find_element(By.TAG_NAME, "body").text
                        store_ids = re.findall(r"smartstore\.naver\.com/([a-zA-Z0-9_-]+)", body_text)
                        found_count = 0
                        
                        for sid in store_ids:
                            if sid.lower() not in ['category', 'notice', 'profile', 'best', 'products', 'search']:
                                email = f"{sid}@naver.com".lower()
                                if email not in existing_emails:
                                    found_count += 1
                                    existing_emails.add(email)
                                    new_data.append({"Email": email, "Keyword": keyword, "Discovered_Date": datetime.now().strftime("%Y-%m-%d"), "Last_Sent_Date": "", "Send_Count": 0, "Template_Used": ""})
                        
                        if found_count > 0: 
                            st.success(f"[{page}페이지] 타겟 {found_count}개 추가!")
                        else:
                            st.warning(f"[{page}페이지] 새로운 이메일을 찾지 못했습니다.")
                            
                    except Exception as e: 
                        pass
                    
                    try:
                        # 다음 페이지 버튼 찾기
                        next_btn = driver.find_element(By.ID, "pnnext")
                        driver.execute_script("arguments[0].scrollIntoView();", next_btn)
                        time.sleep(1)
                        next_btn.click()
                        page += 1
                        time.sleep(3) # 🌟 다음 페이지 로딩 대기
                    except:
                        log_box.warning("마지막 페이지이거나 구글에서 추가 검색을 막았습니다. 수집을 종료합니다.")
                        break
                        
                driver.quit()
                if new_data:
                    df = pd.concat([df, pd.DataFrame(new_data)], ignore_index=True)
                    save_brand_db(df)
                    st.balloons()

    with tab_mail:
        st.subheader("2. 전략적 제휴 제안 메일 발송")
        
        col_name, col_card = st.columns([1, 2])
        with col_name:
            selected_sender_name = st.selectbox("발신자 이름 선택", list(B2B_SENDER_INFO.keys()))
        
        card_path = B2B_SENDER_INFO[selected_sender_name]
        has_card = os.path.exists(card_path)
        with col_card:
            st.write("")
            st.write(f"🪪 **첨부될 명함:** `{card_path}` {'✅ 준비완료' if has_card else '❌ 파일없음 (cards 폴더 확인 필요)'}")
        
        EMAIL_TEMPLATES = get_email_templates(selected_sender_name)
        selected_template_name = st.selectbox("보낼 메일 템플릿을 선택하세요", list(EMAIL_TEMPLATES.keys()))
        selected_template = EMAIL_TEMPLATES[selected_template_name]
        
        with st.expander("👀 발송될 메일 미리보기"):
            preview_body = selected_template['body']
            if has_card: 
                preview_body = preview_body.replace('cid:biz_card', f'data:image/png;base64,{get_image_base64(card_path)}')
            st.components.v1.html(preview_body, height=400, scrolling=True)
        
        col1, col2 = st.columns(2)
        with col1: sender_email = st.text_input("보내는 사람 구글 이메일", value="rizzsender@gmail.com")
        with col2: sender_pw = st.text_input("구글 앱 비밀번호 16자리", type="password")
        
        df = load_brand_db()
        target_df = df[(df['Last_Sent_Date'].isna()) | (df['Last_Sent_Date'] == "") | (df['Send_Count'] == 0)]
        st.write(f"🎯 **최초 발송 대기 중인 타겟: {len(target_df)}곳**")
        
        if st.button("🚀 위 템플릿으로 발송 시작", type="primary"):
            if not sender_pw: st.error("앱 비밀번호를 입력해주세요!")
            elif not has_card: st.error(f"명함 파일({card_path})이 없습니다. 폴더 경로를 확인해 주세요!")
            elif len(target_df) == 0: st.info("현재 새로 보낼 타겟이 없습니다.")
            else:
                progress_bar, status_text = st.progress(0), st.empty()
                success_count = 0
                for i, idx in enumerate(target_df.index):
                    to_email = df.at[idx, 'Email'].replace(' ', '').strip()
                    status_text.write(f"[{i+1}/{len(target_df)}] {to_email} 발송 중...")
                    try:
                        msg = MIMEMultipart('related')
                        msg['From'], msg['To'], msg['Subject'] = sender_email, to_email, Header(selected_template['subject'], 'utf-8')
                        msg.attach(MIMEMultipart('alternative')).attach(MIMEText(selected_template['body'].replace('\xa0', ' '), 'html', 'utf-8'))
                        
                        if has_card:
                            with open(card_path, "rb") as f:
                                img_data = MIMEImage(f.read())
                                img_data.add_header('Content-ID', '<biz_card>')
                                msg.attach(img_data)
                                
                        server = smtplib.SMTP('smtp.gmail.com', 587)
                        server.starttls()
                        server.login(sender_email, sender_pw.replace(' ', ''))
                        server.send_message(msg)
                        server.quit()
                        
                        df.at[idx, 'Last_Sent_Date'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        df.at[idx, 'Send_Count'] = int(df.at[idx, 'Send_Count']) + 1
                        df.at[idx, 'Template_Used'] = selected_template_name.split(']')[0] + "]"
                        save_brand_db(df)
                        success_count += 1
                        time.sleep(2)
                    except Exception as e: st.error(f"{to_email} 발송 실패: {e}")
                    progress_bar.progress((i + 1) / len(target_df))
                status_text.success(f"🎉 총 {success_count}곳에 제안서 발송 완료!")

    with tab_crm:
        st.subheader("📊 B2B 콜드메일 CRM 데이터베이스")
        df = load_brand_db()
        st.dataframe(df, use_container_width=True)