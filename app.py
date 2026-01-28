import streamlit as st
import pandas as pd
import re
import base64
from datetime import datetime
import googleapiclient.discovery
import googleapiclient.errors # API 에러 처리를 위해 추가
import google.generativeai as genai

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

# --- [2. 국가 데이터 설정] ---
COUNTRIES = {
    "대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", 
    "캐나다": "CA", "호주": "AU", "프랑스": "FR", "독일": "DE", 
    "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"
}

# --- [3. UI 설정 및 로고 배치] ---
st.set_page_config(page_title="Glowup Rizz - 글로벌 크리에이터 서치", layout="wide")

# 로고를 왼쪽 사이드바 상단에 배치 (가장 안전하고 유저 친화적인 위치)
with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.warning("⚠️ logo.png 파일을 찾을 수 없습니다.")
    st.markdown("---")
    st.info("💡 **Glowup Rizz v2.0**\n글로벌 유튜브 시장 분석 도구")

# 메인 타이틀
st.title("🌐 글로벌 크리에이터 서치 웹사이트")
st.markdown("전 세계 유튜브 데이터를 분석하여 고효율 크리에이터를 발굴합니다.")
st.markdown("---")

# --- [4. 메인 검색 폼] ---
with st.form("search_form"):
    col1, col2, col3 = st.columns([4, 1.5, 1])
    with col1:
        keywords_input = st.text_input(
            "🔎 검색 키워드", 
            placeholder="애견 카페, Dog Cafe, 강아지 (쉼표로 구분)",
            label_visibility="collapsed"
        )
    with col2:
        selected_country_name = st.selectbox("분석 대상 국가", list(COUNTRIES.keys()))
        selected_region = COUNTRIES[selected_country_name]
    with col3:
        submit_button = st.form_submit_button("🚀 검색 시작")

    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        efficiency_val = st.slider("최소 구독자 대비 조회수 효율 (%)", 0, 100, 30)
        efficiency_target = efficiency_val / 100
    with f_col2:
        min_view_floor = st.number_input("최소 평균 조회수 설정", 0, 1000000, 50000, step=5000)
    with f_col3:
        max_res = st.number_input("키워드당 분석 채널 수", 5, 50, 20)

st.markdown("---")

# --- [5. 로직 함수들] ---

# 헬퍼 함수: API 할당량 초과 에러 감지
def handle_api_error(e):
    if isinstance(e, googleapiclient.errors.HttpError) and e.resp.status == 403:
        # 할당량 소진 시 빨간색 경고 표시
        st.error("🔴 **YouTube API 일일 할당량이 모두 소진되었습니다.**")
        st.error("현재 API 키로는 더 이상 검색이 불가합니다. 내일 다시 시도하거나 다른 API 키를 사용해 주세요.")
        st.stop()
    else:
        st.error(f"⚠️ 오류 발생: {e}")
        st.stop()

def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5:
        return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "AI 분석 어려움 (직접 확인 필요)"
    except: return "데이터 확인 필요"

def is_korean(text):
    return bool(re.search('[ㄱ-ㅎ|가-힣]+', text))

def check_performance(up_id, subs):
    if subs == 0: return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        is_valid = (eff >= efficiency_target) and (avg_v >= min_view_floor)
        return is_valid, avg_v, eff
    except Exception as e:
        if "quotaExceeded" in str(e): handle_api_error(e)
        return False, 0, 0

# --- [6. 실행 프로세스] ---
if submit_button:
    if not keywords_input:
        st.warning("⚠️ 검색어를 입력해주세요.")
        st.stop()
        
    kws = [k.strip() for k in keywords_input.split(",")]
    final_list = []
    
    prog = st.progress(0)
    status_msg = st.empty()
    total = len(kws) * max_res
    curr = 0

    with st.status(f"🔍 {selected_country_name} 데이터 분석 중...", expanded=True) as status:
        try:
            for kw in kws:
                st.write(f"📂 **'{kw}'** 관련 채널 수집 중 ({selected_country_name})...")
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=selected_region).execute()
                
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    title = item['snippet']['title']
                    desc = item['snippet'].get('description', '')
                    status_msg.info(f"⏳ 분석 중: **{title}**")
                    
                    if selected_region == "KR":
                        if not (is_korean(title) or is_korean(desc)): continue

                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        thumb_url = ch['snippet']['thumbnails']['default']['url']
                        
                        is_ok, avg_v, eff = check_performance(ch['contentDetails']['relatedPlaylists']['uploads'], subs)
                        
                        if is_ok:
                            st.write(f"✅ **{title}** 통과! (효율: {eff*100:.1f}%)")
                            email_reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', ch['snippet']['description'])
                            email = email_reg[0] if email_reg else extract_email_ai(ch['snippet']['description'])
                            
                            final_list.append({
                                "채널명": title,
                                "구독자": subs,
                                "최근 10개 평균 조회수": round(avg_v),
                                "조회수 효율": f"{eff*100:.1f}%",
                                "이메일": email,
                                "URL": f"https://youtube.com/channel/{ch['id']}",
                                "프로필": thumb_url,
                            })
                    except Exception as e:
                        if "quotaExceeded" in str(e): handle_api_error(e)
                        continue
        except Exception as e:
            handle_api_error(e)

        status.update(label="✅ 분석 완료!", state="complete", expanded=False)
        status_msg.empty()

    if final_list:
        df = pd.DataFrame(final_list)
        st.subheader(f"📊 {selected_country_name} 검색 결과 (총 {len(final_list)}개 채널)")
        st.data_editor(
            df,
            column_config={
                "프로필": st.column_config.ImageColumn("프로필", width="small"),
                "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
                "최근 10개 평균 조회수": st.column_config.NumberColumn(format="%d회")
            },
            use_container_width=True, hide_index=True, disabled=True
        )
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            f"📥 {selected_country_name} 결과 다운로드", 
            data=csv, 
            file_name=f"Global_Creator_{selected_region}_{datetime.now().strftime('%m%d')}.csv",
            use_container_width=True
        )
    else:
        st.warning(f"🧐 {selected_country_name}에서 조건에 맞는 채널을 찾지 못했습니다.")
