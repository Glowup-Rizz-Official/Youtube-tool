import streamlit as st
import pandas as pd
import re
import base64
import time  # 1. 속도 조절을 위해 새로 추가되었습니다!
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

# --- [2. 데이터 설정] ---
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

# --- [3. UI 설정] ---
st.set_page_config(page_title="Glowup Rizz - YOUTUBE 검색 엔진", layout="wide")

with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        pass
    st.markdown("---")
    st.info("🚀 **Glowup Rizz v3.9**\nAI 과부하 방지 시스템 가동 중")

st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [4. 메인 검색 폼] ---
with st.form("search_form"):
    st.markdown("📥 **기존 리스트 제외하기 (선택 사항)**")
    exclude_file = st.file_uploader("이미 확보한 채널 리스트(엑셀/CSV)를 업로드하면 검색 결과에서 제외됩니다.", type=['xlsx', 'csv'])
    st.markdown("---")
    
    r1_col1, r1_col2, r1_col3 = st.columns([4, 1.2, 0.8])
    with r1_col1:
        keywords_input = st.text_input("🔎 검색 키워드", placeholder="애견 카페, 강아지 (쉼표 구분)", label_visibility="collapsed")
    with r1_col2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()), label_visibility="collapsed")
    with r1_col3:
        submit_button = st.form_submit_button("🚀 검색")

    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        selected_sub_range = st.selectbox("🎯 구독자 범위 선택", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2:
        efficiency_target = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30) / 100
    with r2_col3:
        max_res = st.number_input("🔍 키워드당 분석 수", 5, 50, 20)

st.markdown("---")

# --- [5. 로직 함수들] ---
def extract_exclude_list(file):
    try:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        exclude_set = set()
        for col in df.columns:
            exclude_set.update(df[col].astype(str).str.strip().tolist())
        return exclude_set
    except: return set()

def handle_api_error(e):
    if "quotaExceeded" in str(e):
        st.error("🔴 **YouTube API 할당량이 소진되었습니다.** 내일 다시 시도해 주세요.")
        st.stop()
    else: st.error(f"⚠️ 오류 발생: {e}")

# [수정됨] 이메일 추출 시 AI 과부하 방지 퓨즈 설치
def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5: return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        time.sleep(1) # AI에게 생각할 시간(1초)을 주어 과부하 방지
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
    except Exception as e:
        if "quotaExceeded" in str(e): handle_api_error(e)
        return False, 0, 0

# [수정됨] 딥리서치 AI 광고 판별 시 과부하 방지 퓨즈 설치
# --- [수정된 핵심 함수: 공식 표기 감지 + AI 정밀 분석] ---
def get_recent_ad_videos_ai(up_id, count):
    try:
        # 1. 영상 데이터 수집
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        all_videos = []
        ad_found_indices = [] # 공식 표기로 찾은 광고 인덱스 저장

        # 공식 광고 표기 패턴 (유튜브 가이드라인 및 공정위 기준)
        official_patterns = [
            "유료 광고 포함", "Paid promotion", "제작 지원", "유료 협찬", 
            "#광고", "#협찬", "Product provided", "Sponsored"
        ]

        for idx, v in enumerate(v_res.get('items', [])):
            title = v['snippet']['title']
            desc = v['snippet'].get('description', '')
            
            video_data = {
                "영상 제목": title,
                "설명": desc[:1000],
                "업로드 일자": datetime.strptime(v['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d'),
                "조회수": int(v['statistics'].get('viewCount', 0)),
                "영상 링크": f"https://youtu.be/{v['id']}",
                "판단근거": ""
            }

            # 1단계: 프로그램이 '공식 문구'를 직접 검사 (매우 빠름)
            for pattern in official_patterns:
                if pattern in title or pattern in desc[:200]: # 제목이나 설명란 앞부분 집중 검사
                    video_data["판단근거"] = f"공식 표기 감지({pattern})"
                    ad_found_indices.append(idx)
                    break
            
            all_videos.append(video_data)
        
        if not all_videos: return pd.DataFrame()

        # 2단계: 공식 표기가 없는 영상들만 모아서 AI에게 2차 판별 요청 (AX 강화)
        remaining_indices = [i for i in range(len(all_videos)) if i not in ad_found_indices]
        
        if remaining_indices:
            video_text = "\n".join([f"[{i}] 제목: {all_videos[i]['영상 제목']} / 설명: {all_videos[i]['설명'][:150]}" for i in remaining_indices])
            prompt = f"""
            다음 유튜브 영상 리스트에서 '공식 표기는 없지만' 광고나 협찬이 확실해 보이는 영상을 골라줘.
            (예: 할인코드 제공, 특정 브랜드 쇼핑몰 링크, 제품 제공 언급 등)
            광고가 없다면 'None'이라고 답해. 형식: 0, 2, 5
            
            리스트:
            {video_text}
            """
            
            try:
                time.sleep(1) # 할당량 보호
                response = model.generate_content(prompt)
                ai_res = response.text.strip()
                if "None" not in ai_res:
                    ai_indices = [int(i.strip()) for i in ai_res.split(",") if i.strip().isdigit()]
                    for i in ai_indices:
                        if i < len(all_videos):
                            all_videos[i]["판단근거"] = "AI 정밀 분석 감지"
                            ad_found_indices.append(i)
            except Exception as e:
                if "429" in str(e):
                    st.caption("⚠️ AI 2차 분석은 할당량 초과로 건너뜁니다. (공식 표기 위주로 표시)")
                pass

        # 3단계: 최종 광고 영상 리스트 구성 (중복 제거 및 정렬)
        final_ad_indices = sorted(list(set(ad_found_indices)))
        ad_videos = [all_videos[i] for i in final_ad_indices]
        
        return pd.DataFrame(ad_videos)[["영상 제목", "업로드 일자", "조회수", "판단근거", "영상 링크"]]
    except: return pd.DataFrame()

# --- [6. 실행 프로세스] ---
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if submit_button:
    if not keywords_input:
        st.warning("⚠️ 검색어를 입력해주세요.")
    else:
        exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        prog = st.progress(0)
        curr = 0
        total = len(kws) * max_res

        with st.status("🔍 데이터 수집 및 AI Transformation 분석 중...", expanded=True) as status:
            for kw in kws:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    title = item['snippet']['title']
                    channel_id = item['snippet']['channelId']
                    channel_url = f"https://youtube.com/channel/{channel_id}"
                    
                    if title.strip() in exclude_data or channel_url in exclude_data or channel_id in exclude_data:
                        continue

                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=channel_id).execute()['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        if is_ok:
                            final_list.append({
                                "채널명": title, "구독자": subs, "평균 조회수": round(avg_v),
                                "효율": f"{eff*100:.1f}%", "이메일": extract_email_ai(ch['snippet']['description']),
                                "URL": channel_url, "프로필": ch['snippet']['thumbnails']['default']['url'],
                                "upload_id": up_id
                            })
                    except: continue
            status.update(label="✅ 분석 완료!", state="complete", expanded=False)
        st.session_state.search_results = pd.DataFrame(final_list)

# --- [7. 결과 출력 및 AI 광고 딥리서치] ---
if isinstance(st.session_state.search_results, pd.DataFrame) and not st.session_state.search_results.empty:
    st.subheader("📊 분석 결과")
    st.caption("💡 채널을 클릭하면 하단에 AI가 판별한 '최근 광고/협업 영상' 리스트가 나타납니다.")
    
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "프로필": st.column_config.ImageColumn("프로필", width="small"),
            "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
            "구독자": st.column_config.NumberColumn(format="%d명"),
            "평균 조회수": st.column_config.NumberColumn(format="%d회"),
            "upload_id": None
        },
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        st.markdown("---")
        st.subheader(f"🔍 '{ch_info['채널명']}' AI 광고 분석")
        
        analysis_count = st.selectbox("분석 범위 설정 (최근 영상)", [10, 20, 30], index=1)
        
        with st.spinner(f"AI로 최근 광고 협업 사례를 찾는 중입니다..."):
            ad_df = get_recent_ad_videos_ai(ch_info['upload_id'], analysis_count)
            
            if not ad_df.empty:
                st.success(f"🎯 총 {len(ad_df)}개의 최근 광고/협업 영상이 감지되었습니다.")
                st.dataframe(
                    ad_df,
                    column_config={"영상 링크": st.column_config.LinkColumn("영상 보기", display_text="이동"), "조회수": st.column_config.NumberColumn(format="%d회")},
                    use_container_width=True, hide_index=True
                )
                csv = ad_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(f"📥 {ch_info['채널명']} 광고 리스트 다운로드", data=csv, file_name=f"Ads_{ch_info['채널명']}.csv")
            else:
                st.warning("🧐 분석 범위 내에서 최근 광고 협업 영상이 감지되지 않았습니다.")
