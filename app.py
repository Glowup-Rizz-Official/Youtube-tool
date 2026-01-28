import streamlit as st
import pandas as pd
import re
import base64
from datetime import datetime
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

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. 국가 및 구독자 구간 데이터 설정] ---
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

# --- [3. UI 설정 및 로고 배치] ---
st.set_page_config(page_title="Glowup Rizz - 고효율 크리에이터 서치", layout="wide")

# 사이드바에 로고와 간단한 설명 배치
with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        pass
    st.markdown("---")
    st.info("🚀 **Glowup Rizz v2.5**\n효율 중심 글로벌 분석 도구")

# 메인 타이틀
st.title("🌐 고효율 크리에이터 서치 엔진")
st.markdown("구독자 규모와 조회수 효율을 바탕으로 가장 강력한 채널을 찾습니다.")
st.markdown("---")

# --- [4. 메인 검색 폼 (정렬 및 필터 개선)] ---
with st.form("search_form"):
    # 첫 번째 줄: 검색창 / 국가 / 버튼 (비율 조정으로 정렬)
    r1_col1, r1_col2, r1_col3 = st.columns([4, 1.2, 0.8])
    with r1_col1:
        keywords_input = st.text_input(
            "🔎 검색 키워드", 
            placeholder="애견 카페, 강아지 (쉼표 구분)",
            label_visibility="collapsed"
        )
    with r1_col2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()), label_visibility="collapsed")
    with r1_col3:
        submit_button = st.form_submit_button("🚀 검색")

    # 두 번째 줄: 구독자 구간 / 조회수 효율 / 분석 수 (균등 배분)
    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        selected_sub_range = st.selectbox("🎯 구독자 범위 선택", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2:
        efficiency_val = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30, help="구독자 수 대비 평균 조회수 비율")
        efficiency_target = efficiency_val / 100
    with r2_col3:
        max_res = st.number_input("🔍 키워드당 분석 수", 5, 50, 20)

st.markdown("---")

# --- [5. 로직 함수들] ---
def handle_api_error(e):
    if "quotaExceeded" in str(e):
        st.error("🔴 **YouTube API 할당량이 소진되었습니다.** 내일 다시 시도해 주세요.")
        st.stop()
    else:
        st.error(f"⚠️ 오류 발생: {e}")

def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5: return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "AI 분석 어려움 (직접 확인 필요)"
    except: return "데이터 확인 필요"

def check_performance(up_id, subs):
    if subs == 0: return False, 0, 0
    # 구독자 수 범위 체크 우선 실행
    if not (min_subs <= subs <= max_subs): return False, 0, 0
    
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        
        # 효율 조건만 체크 (평균 조회수 하한선 제거)
        is_valid = (eff >= efficiency_target)
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
    region_code = COUNTRIES[selected_country]
    final_list = []
    
    prog = st.progress(0)
    status_msg = st.empty()
    total = len(kws) * max_res
    curr = 0

    with st.status(f"🔍 {selected_country} / {selected_sub_range} 분석 중...", expanded=True) as status:
        try:
            for kw in kws:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=region_code).execute()
                
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    title = item['snippet']['title']
                    status_msg.info(f"⏳ 분석 중: **{title}**")

                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        
                        is_ok, avg_v, eff = check_performance(ch['contentDetails']['relatedPlaylists']['uploads'], subs)
                        
                        if is_ok:
                            st.write(f"✨ **{title}** 통과! (구독자: {subs:,}명 / 효율: {eff*100:.1f}%)")
                            desc = ch['snippet']['description']
                            email_reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
                            email = email_reg[0] if email_reg else extract_email_ai(desc)
                            
                            final_list.append({
                                "채널명": title,
                                "구독자": subs,
                                "평균 조회수": round(avg_v),
                                "조회수 효율": f"{eff*100:.1f}%",
                                "이메일": email,
                                "URL": f"https://youtube.com/channel/{ch['id']}",
                                "프로필": ch['snippet']['thumbnails']['default']['url'],
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
        st.subheader(f"📊 검색 결과 (총 {len(final_list)}개)")
        st.data_editor(
            df,
            column_config={
                "프로필": st.column_config.ImageColumn("프로필", width="small"),
                "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
                "구독자": st.column_config.NumberColumn(format="%d명"),
                "평균 조회수": st.column_config.NumberColumn(format="%d회")
            },
            use_container_width=True, hide_index=True, disabled=True
        )
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 결과 다운로드 (CSV)", data=csv, file_name=f"Glowup_Rizz_{datetime.now().strftime('%m%d')}.csv", use_container_width=True)
    else:
        st.warning("🧐 조건에 맞는 채널을 찾지 못했습니다. 구독자 범위나 효율을 조정해 보세요.")
