import streamlit as st
import pandas as pd
import re
import base64  # 로고 처리를 위해 추가
from datetime import datetime
import googleapiclient.discovery
import google.generativeai as genai

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash') # 최신 모델명으로 유지
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. UI 설정 및 로고 고정] ---
st.set_page_config(page_title="유튜브 크리에이터 서치", layout="wide")

# 로고를 오른쪽 상단에 고정하는 함수
def add_logo(logo_path):
    try:
        with open(logo_path, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode()
        st.markdown(
            f"""
            <style>
            [data-testid="stAppViewContainer"]::before {{
                content: "";
                position: fixed;
                top: 60px;       /* 15px에서 60px로 대폭 내려서 버튼 아래로 피신! */
                right: 30px;     /* 다시 오른쪽 구석으로 배치 */
                width: 130px;    /* 로고 크기 */
                height: 60px;
                background-image: url("data:image/png;base64,{encoded}");
                background-size: contain;
                background-repeat: no-repeat;
                background-position: right top;
                z-index: 1001;   /* 우선순위를 더 높임 */
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    except FileNotFoundError:
        st.sidebar.warning("⚠️ logo.png 파일을 찾을 수 없습니다.")

# 로고 실행
add_logo("logo.png")

st.title("🌐 유튜브 크리에이터 서치 웹사이트")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 검색 필터")
    keywords_input = st.text_input(
        "검색 키워드 (쉼표 구분)", 
        placeholder="애견 카페, 강아지, 고양이"
    )
    efficiency_target = st.slider("최소 구독자 대비 조회수 효율 (%)", 0, 100, 30) / 100
    min_view_floor = st.number_input("최소 평균 조회수 설정", 0, 500000, 50000, step=5000)
    max_res = st.number_input("키워드당 분석 채널 수", 5, 50, 20)

# --- [3. 로직 함수들] ---
def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5:
        return "설명란 없음 (직접 확인)"
    
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50:
            return res
        return "직접 확인 필요"
    except:
        return "AI 검색 실패"

def is_korean(text):
    return bool(re.search('[ㄱ-ㅎ|가-힣]+', text))

def check_performance(up_id, subs):
    if subs == 0: return False, 0, 0
    try:
        # 최근 영상 15개를 가져와서 쇼츠 필터링
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        
        # 롱폼 영상(분/시간 단위 포함)만 최대 10개 추출
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        
        if not longforms: return False, 0, 0
        
        # 실제 분석된 영상 개수로 평균 계산 (최대 10개)
        # $Avg = \frac{\sum_{i=1}^{n} Views_i}{n}$ (n ≤ 10)
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        
        is_valid = (eff >= efficiency_target) and (avg_v >= min_view_floor)
        return is_valid, avg_v, eff
    except: return False, 0, 0

# --- [4. 실행 프로세스] ---
if st.button("🚀 크리에이터 검색 시작"):
    if not keywords_input:
        st.warning("검색어를 입력해주세요.")
        st.stop()
        
    kws = [k.strip() for k in keywords_input.split(",")]
    final_list = []
    
    prog = st.progress(0)
    status_msg = st.empty()
    total = len(kws) * max_res
    curr = 0

    with st.status("🔍 유튜버 분석 중...", expanded=True) as status:
        for kw in kws:
            st.write(f"📂 **'{kw}'** 검색 중...")
            search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode="KR").execute()
            
            for item in search['items']:
                curr += 1
                prog.progress(min(curr/total, 1.0))
                
                title = item['snippet']['title']
                desc = item['snippet'].get('description', '')
                status_msg.info(f"⏳ 분석 중: **{title}**")
                
                if not (is_korean(title) or is_korean(desc)):
                    continue

                ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                subs = int(ch['statistics'].get('subscriberCount', 0))
                thumb_url = ch['snippet']['thumbnails']['default']['url']
                
                is_ok, avg_v, eff = check_performance(ch['contentDetails']['relatedPlaylists']['uploads'], subs)
                
                if is_ok:
                    st.write(f"✨ **{title}** 통과! (최근 10개 영상 평균 조회수: {avg_v:,.0f}회)")
                    
                    email_reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', ch['snippet']['description'])
                    email = email_reg[0] if email_reg else extract_email_ai(ch['snippet']['description'])
                    
                    final_list.append({
                        "채널명": title,
                        "구독자": subs,
                        "최근 10개 영상 평균 조회수": round(avg_v), # 컬럼명 수정
                        "조회수 효율": f"{eff*100:.1f}%",
                        "이메일": email,
                        "URL": f"https://youtube.com/channel/{ch['id']}",
                        "프로필": thumb_url,
                    })

        status.update(label="✅ 검색 완료!", state="complete", expanded=False)
        status_msg.empty()

    if final_list:
        df = pd.DataFrame(final_list)
        st.data_editor(
            df,
            column_config={
                "프로필": st.column_config.ImageColumn("프로필", width="small"),
                "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
                "최근 10개 영상 평균 조회수": st.column_config.NumberColumn(format="%d회") # 숫자 포맷 추가
            },
            use_container_width=True,
            hide_index=True,
            disabled=True
        )
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 검색 결과 엑셀 다운로드", data=csv, file_name=f"Creator_Search_{datetime.now().strftime('%m%d')}.csv")
    else:
        st.warning("조건에 맞는 한국인 크리에이터를 찾지 못했습니다.")
