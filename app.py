import streamlit as st
import pandas as pd
import re
import time
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timedelta, timezone

import googleapiclient.discovery
import googleapiclient.errors
import google.generativeai as genai

# --- [1. Security & API Setup] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
    EMAIL_USER = st.secrets["EMAIL_USER"]
    EMAIL_PW = st.secrets["EMAIL_PW"]
except KeyError:
    st.error("🚨 Please check security settings (.streamlit/secrets.toml).")
    st.stop()

# Initialize API
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. Data & Constants Settings] ---
# Translate Countries for UI
COUNTRIES = {
    "South Korea": "KR", "USA": "US", "Japan": "JP", 
    "UK": "GB", "Vietnam": "VN", "Thailand": "TH", 
    "Indonesia": "ID", "Taiwan": "TW"
}

# Translate Subscriber Ranges for UI
SUB_RANGES = {
    "All": (0, 100000000), 
    "Under 10k": (0, 10000), 
    "10k ~ 50k": (10000, 50000), 
    "50k ~ 100k": (50000, 100000), 
    "100k ~ 500k": (100000, 500000), 
    "500k ~ 1M": (500000, 1000000), 
    "Over 1M": (1000000, 100000000)
}

# Templates
TEMPLATES = {
    "Template 1 (Home Service Proposal)": {
        "title": "[Glowup Rizz X {name}] Collaboration Proposal",
        "body": """안녕하세요, {name}님!<br>
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.<br><br>
(This is a Korean proposal template for Home Service ads...)<br>
...<br>
{sender} 드림"""
    },
    "Template 2 (Beauty Device Proposal)": {
        "title": "[Glowup Rizz X {name}] Beauty Device Proposal",
        "body": """안녕하세요, {name} 계정 담당자님!<br>
글로우업리즈 콘텐츠 비즈니스팀 {sender} 이라고 합니다.<br><br>
(This is a Korean proposal template for Beauty Devices...)<br>
...<br>
{sender} 드림."""
    }
}

# --- [3. DB & State Management] ---
st.set_page_config(page_title="Glowup Rizz Creator Analysis Engine", layout="wide")

if "search_results" not in st.session_state: st.session_state.search_results = None

def init_db():
    conn = sqlite3.connect('mail_log.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS send_log (channel_name TEXT, email TEXT, status TEXT, sent_at TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS api_usage 
                 (id INTEGER PRIMARY KEY, youtube_count INTEGER, ai_count INTEGER, last_reset TEXT)''')
    c.execute("SELECT count(*) FROM api_usage")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO api_usage (id, youtube_count, ai_count, last_reset) VALUES (1, 0, 0, ?)", 
                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    conn.commit()
    conn.close()

init_db()

# --- [4. Core Logic Functions] ---

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

def send_custom_mail(receiver_email, subject, body, channel_name, sender_name, image_file=None):
    if not receiver_email or "@" not in receiver_email:
        return False, "Invalid Email"
    
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{EMAIL_USER}>"
    msg['To'] = receiver_email
    msg['Reply-To'] = "partner@glowuprizz.com"

    html_content = f"""
    <html>
    <body>
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
            {body}
        </div>
    """
    
    if image_file is not None:
        html_content += """
        <br><br>
        <img src="cid:business_card" alt="Business Card" style="max-width: 100%; height: auto; border: 1px solid #ddd;">
        """
    html_content += "</body></html>"

    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(html_content, 'html', 'utf-8'))

    if image_file is not None:
        try:
            image_file.seek(0)
            img_data = image_file.read()
            image = MIMEImage(img_data)
            image.add_header('Content-ID', '<business_card>')
            image.add_header('Content-Disposition', 'inline', filename='business_card.png')
            msg.attach(image)
        except Exception as e:
            return False, f"Image Error: {str(e)}"

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PW)
            server.sendmail(EMAIL_USER, receiver_email, msg.as_string())
        save_log(channel_name, receiver_email, "Success")
        return True, "Success"
    except Exception as e:
        save_log(channel_name, receiver_email, f"Failed: {str(e)}")
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
        manage_api_quota(ai_add=1)
        response = model.generate_content(f"Extract email address from this text. If none, return None: {desc}")
        res = response.text.strip()
        return res if "@" in res else "None"
    except: return "None"

# --- 수정된 성능 평가 함수 (참여도, 업로드 빈도 계산) ---
def check_performance(up_id, subs):
    try:
        manage_api_quota(yt_add=1)
        # 업로드 날짜를 가져오기 위해 snippet 추가
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=10).execute()
        items = req.get('items', [])
        if not items: return False, 0, 0, 0, "N/A"

        v_ids = [i['contentDetails']['videoId'] for i in items]
        
        # [Upload Frequency 계산 로직] (최근 10개 영상 기준)
        dates = [datetime.strptime(i['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ') for i in items]
        if len(dates) > 1:
            days_diff = (max(dates) - min(dates)).days
            freq_days = max(1, days_diff // len(dates))
            freq_str = f"1 video / {freq_days} days" # 예: 1 video / 5 days
        else:
            freq_str = "N/A"

        manage_api_quota(yt_add=1)
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']]
        if not longforms: return False, 0, 0, 0, "N/A"
        
        total_views = 0
        total_engagement = 0 # 좋아요 + 댓글
        
        for v in longforms:
            stats = v['statistics']
            views = int(stats.get('viewCount', 0))
            likes = int(stats.get('likeCount', 0))
            comments = int(stats.get('commentCount', 0))
            
            total_views += views
            total_engagement += (likes + comments)

        avg_v = total_views / len(longforms)
        eff = avg_v / subs if subs > 0 else 0
        
        # [Average Engagement 계산 로직] (조회수 대비 좋아요+댓글 비율)
        engagement_rate = (total_engagement / total_views * 100) if total_views > 0 else 0

        return True, avg_v, eff, engagement_rate, freq_str
    except: return False, 0, 0, 0, "N/A"

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
                "Video Title": title, 
                "Upload Date": pub[:10], 
                "Views": int(v['statistics'].get('viewCount',0)), 
                "Link": f"https://youtu.be/{v['id']}" 
            }
            if any(p in title for p in patterns) or any(p in desc for p in patterns):
                ad_indices.append(idx)
            all_videos.append(vid_data)
            
        remaining = [i for i in range(len(all_videos)) if i not in ad_indices]
        if remaining:
            prompt = "".join([f"[{i}] Title:{all_videos[i]['Video Title']} / Desc:{v_res['items'][i]['snippet']['description'][:300]}\n" for i in remaining])
            try:
                manage_api_quota(ai_add=1)
                resp = model.generate_content(f"Return indices of videos that look like ads/sponsorships (comma separated):\n{prompt}")
                ad_indices.extend([int(x) for x in re.findall(r'\d+', resp.text)])
            except: pass
        final_ads = [all_videos[i] for i in sorted(list(set(ad_indices))) if i < len(all_videos)]
        return pd.DataFrame(final_ads)
    except: return pd.DataFrame()

# --- [5. Sidebar UI: Admin & Logs (English)] ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    
    yt_used, ai_used = manage_api_quota()
    st.markdown("### 📊 Team Resource Status")
    
    yt_limit = 500000 
    st.progress(min(yt_used / yt_limit, 1.0))
    st.caption(f"📺 YouTube API: {yt_used:,} / {yt_limit:,} (Resets at 5 PM)")
    
    st.markdown("---")
    st.write(f"🤖 **AI API Call Count:** {ai_used:,}")
    
    if st.checkbox("📋 View Real-time Email Logs"):
        try:
            conn = sqlite3.connect('mail_log.db')
            log_df = pd.read_sql_query("SELECT * FROM send_log ORDER BY sent_at DESC", conn)
            log_df.columns = ['Channel Name', 'Email', 'Status', 'Sent At']
            st.dataframe(log_df, use_container_width=True, hide_index=True)
            conn.close()
        except: st.write("No logs available.")
            
    st.markdown("---")
    
    admin_pw = st.text_input("🔓 Admin Mode", type="password")
    
    try:
        secret_pw = st.secrets["ADMIN_PASSWORD"]
    except:
        secret_pw = "rizz"

    if admin_pw == secret_pw:
        st.success("✅ Admin Verified")
        
        if st.button("🔄 Reset AI Count (Monthly Recommendation)"):
            reset_ai_quota()
            st.rerun()

# --- [6. Main Search UI (English)] ---
st.title("🌐 YouTube Creator Search Engine")
with st.form("search"):
    exclude_file = st.file_uploader("Exclude Channel List (Excel/CSV)", type=['xlsx', 'csv'])
    kws = st.text_input("Search Keywords (comma separated)")
    
    c1, c2, c3 = st.columns(3)
    with c1: selected_country = st.selectbox("Country", list(COUNTRIES.keys()))
    with c2: 
        sub_range = st.selectbox("Subscriber Range", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[sub_range]
    with c3: max_res = st.number_input("Sample Size", 5, 50, 20)
    
    c4, c5 = st.columns(2)
    with c4: search_mode = st.radio("Search Mode", ["Video Based (Recommended)", "Channel Based"], horizontal=True)
    with c5: eff_target = st.slider("Min Efficiency (%)", 0, 100, 30) / 100
    
    btn = st.form_submit_button("🚀 Start Analysis")

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
            if "Video" in search_mode:
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
                
                is_ok, avg_v, eff, eng_rate, freq = check_performance(upid, subs)
                
                if is_ok and eff >= eff_target:
                    email = extract_email_ai(ch['snippet']['description'])
                    final_list.append({
                        "Channel Name": title, 
                        "Subscribers": subs, 
                        "Avg Views": int(avg_v), 
                        "Efficiency": f"{eff*100:.1f}%",
                        "Avg Engagement": f"{eng_rate:.2f}%", 
                        "Upload Frequency": freq,             
                        "Email": email, 
                        "Profile": ch['snippet']['thumbnails']['default']['url'],
                        "URL": url, 
                        "upload_id": upid
                    })
        except: break
    st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. Results & Proposal UI (English)] ---
if "search_results" in st.session_state and st.session_state.search_results is not None:
    st.subheader("📊 Analysis Results")
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "Profile": st.column_config.ImageColumn(),
            "URL": st.column_config.LinkColumn("Go to Channel", display_text="Visit"),
            "upload_id": None
        },
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        row = st.session_state.search_results.iloc[event.selection.rows[0]]
        st.divider()
        
        # [A] Deep Research
        st.subheader(f"🔍 Deep Research: {row['Channel Name']}")
        if st.button("Analyze Ad History"):
            with st.spinner("Analyzing..."):
                df = get_recent_ad_videos_ai(row['upload_id'], 20)
                if not df.empty:
                    st.error(f"🚨 Found {len(df)} potential ad videos")
                    st.dataframe(
                        df, 
                        column_config={"Link": st.column_config.LinkColumn("Watch Video", display_text="Watch")},
                        use_container_width=True
                    )
                else: st.success("✅ No ad history found in the last year")
            
        st.divider()
        
        # [B] Draft Email
        st.subheader("📧 Draft Proposal Email")
        col1, col2, col3 = st.columns(3)
        with col1: sender = st.text_input("Marketer Name", value="Minjun Kim")
        with col2: target_email = st.text_input("Recipient Email", value=row['Email'])
        with col3: st.text_input("Reply-To Address", value="partner@glowuprizz.com", disabled=True)
        
        tpl_key = st.selectbox("Select Template", list(TEMPLATES.keys()))
        tpl = TEMPLATES[tpl_key]
        def_sub = tpl['title'].format(name=row['Channel Name'], sender=sender)
        def_body = tpl['body'].format(name=row['Channel Name'], sender=sender)
        
        sub_final = st.text_input("Subject", value=def_sub)
        body_final = st.text_area("Body (HTML allowed)", value=def_body, height=400)
        
        # Business Card
        st.markdown("---")
        st.write("🖼️ **Attach Business Card (Optional)**")
        uploaded_card = st.file_uploader("Upload Card File (JPG, PNG)", type=['png', 'jpg', 'jpeg'])

        with st.expander("👀 Email Preview (Recipient View)", expanded=True):
            st.markdown(f"**To:** {target_email}")
            st.markdown(f"**Subject:** {sub_final}")
            st.markdown("---")
            st.markdown(body_final, unsafe_allow_html=True)
            if uploaded_card:
                st.markdown("<br>", unsafe_allow_html=True)
                st.image(uploaded_card, caption="[Business Card Image Placeholder]", width=300)
            st.markdown("---")
            
        if st.button("🚀 Send Email"):
            if "@" not in target_email:
                st.error("Please check the email address.")
            else:
                with st.spinner("Sending..."):
                    ok, msg = send_custom_mail(target_email, sub_final, body_final, row['Channel Name'], sender, uploaded_card)
                    if ok: st.success("Sent Successfully!")
                    else: st.error(f"Send Failed: {msg}")
