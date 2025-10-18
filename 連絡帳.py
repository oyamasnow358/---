# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
import io
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- Streamlit Secretsからの設定読み込み ---
# .streamlit/secrets.toml に設定してください。

# --- 定数設定 ---
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]


# アプリケーション設定
GENERAL_CONTACTS_SHEET_ID = st.secrets["app_settings"]["general_contacts_sheet_id"]
STUDENTS_SHEET_ID = st.secrets["app_settings"]["students_sheet_id"]
TEACHERS_SHEET_ID = st.secrets["app_settings"]["teachers_sheet_id"]
SUPPORT_MEMO_SHEET_ID = st.secrets["app_settings"]["support_memo_sheet_id"]
CALENDAR_SHEET_ID = st.secrets["app_settings"]["calendar_sheet_id"]
DRIVE_FOLDER_ID = st.secrets["app_settings"]["drive_folder_id"]

# --- Streamlitセッション状態の初期化 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'credentials' not in st.session_state:
    st.session_state.credentials = None
if 'user_info' not in st.session_state:
    st.session_state.user_info = None
if 'user_role' not in st.session_state:
    st.session_state.user_role = None # 'teacher' or 'parent'
if 'associated_students_data' not in st.session_state:
    st.session_state.associated_students_data = [] # {student_name: "", individual_sheet_id: ""}

# --- ヘルパー関数 ---
def get_service_account_info():
    """Streamlit SecretsからGspreadサービスアカウント情報を取得"""
    return {
        "type": st.secrets["gspread_service_account"]["type"],
        "project_id": st.secrets["gspread_service_account"]["project_id"],
        "private_key_id": st.secrets["gspread_service_account"]["private_key_id"],
        "private_key": st.secrets["gspread_service_account"]["private_key"].replace("\\n", "\n"),
        "client_email": st.secrets["gspread_service_account"]["client_email"],
        "client_id": st.secrets["gspread_service_account"]["client_id"],
        "auth_uri": st.secrets["gspread_service_account"]["auth_uri"],
        "token_uri": st.secrets["gspread_service_account"]["token_uri"],
        "auth_provider_x509_cert_url": st.secrets["gspread_service_account"]["auth_provider_x509_cert_url"],
        "client_x509_cert_url": st.secrets["gspread_service_account"]["client_x509_cert_url"],
        "universe_domain": st.secrets["gspread_service_account"]["universe_domain"]
    }

@st.cache_resource(ttl=3600)
def get_gspread_client():
    """Gspreadクライアントを初期化（サービスアカウント認証）"""
    try:
        service_account_info = get_service_account_info()
        gc = gspread.service_account_from_dict(service_account_info)
        return gc
    except Exception as e:
        st.error(f"Gspreadクライアントの初期化に失敗しました: {e}")
        return None

@st.cache_data(ttl=60)
def load_sheet_data(spreadsheet_id, worksheet_name="シート1"): # デフォルトは「シート1」とする
    """Googleスプレッドシートから指定シートのデータを読み込む"""
    gc = get_gspread_client()
    if gc is None:
        return pd.DataFrame()
    try:
        spreadsheet = gc.open_by_id(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.warning(f"スプレッドシートID '{spreadsheet_id}' 内のシート '{worksheet_name}' が見つかりません。")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"スプレッドシートID '{spreadsheet_id}' の読み込み中にエラーが発生しました: {e}")
        return pd.DataFrame()

def append_row_to_sheet(spreadsheet_id, new_record, worksheet_name="シート1"):
    """Googleスプレッドシートにデータを追加する"""
    gc = get_gspread_client()
    if gc is None:
        return False
    try:
        spreadsheet = gc.open_by_id(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        header = worksheet.row_values(1)
        ordered_record = [new_record.get(col, '') for col in header]
        worksheet.append_row(ordered_record)
        st.cache_data.clear() # キャッシュをクリアして最新データを再読み込み
        return True
    except Exception as e:
        st.error(f"スプレッドシートID '{spreadsheet_id}' へのデータ追加中にエラーが発生しました: {e}")
        return False

def update_row_in_sheet(spreadsheet_id, row_index, data_to_update, worksheet_name="シート1"):
    """Googleスプレッドシートの指定行を更新する"""
    gc = get_gspread_client()
    if gc is None:
        return False
    try:
        spreadsheet = gc.open_by_id(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        header = worksheet.row_values(1)
        for col_name, value in data_to_update.items():
            if col_name in header:
                col_index = header.index(col_name) + 1 # gspreadは1-indexed
                worksheet.update_cell(row_index, col_index, value)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"スプレッドシートID '{spreadsheet_id}' の行更新中にエラーが発生しました: {e}")
        return False

def upload_to_drive(file_obj, file_name, mime_type, credentials):
    """Google Driveにファイルをアップロードし、共有可能なURLを返す"""
    try:
        drive_service = build('drive', 'v3', credentials=credentials)
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaFileUpload(
            io.BytesIO(file_obj.read()),
            mimetype=mime_type,
            resumable=True
        )
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        file_id = uploaded_file.get('id')
        web_view_link = uploaded_file.get('webViewLink')

        # 共有設定: リンクを知っている全員が閲覧可能にする
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
            fields='id'
        ).execute()

        return web_view_link
    except Exception as e:
        st.error(f"Google Driveへのアップロード中にエラーが発生しました: {e}")
        return None

# --- Google OAuth認証関数 ---
def authenticate_google_oauth():
    creds = st.session_state.credentials

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state.credentials = creds
            except Exception as e:
                st.error(f"トークンのリフレッシュに失敗しました: {e}")
                st.session_state.credentials = None
                creds = None
        
        if not creds:
            client_config = {
                "web": {
                    "client_id": st.secrets["gcp_oauth"]["client_id"],
                    "project_id": st.secrets["gcp_oauth"]["project_id"],
                    "auth_uri": st.secrets["gcp_oauth"]["auth_uri"],
                    "token_uri": st.secrets["gcp_oauth"]["token_uri"],
                    "auth_provider_x509_cert_url": st.secrets["gcp_oauth"]["auth_provider_x509_cert_url"],
                    "client_secret": st.secrets["gcp_oauth"]["client_secret"],
                    "redirect_uris": st.secrets["gcp_oauth"]["redirect_uris"],
                    "javascript_origins": st.secrets["gcp_oauth"]["javascript_origins"]
                }
            }
            redirect_uri = st.secrets["gcp_oauth"]["redirect_uris"][0]

            flow = Flow.from_client_config(
                client_config, SCOPES,
                redirect_uri=redirect_uri
            )
            auth_url, _ = flow.authorization_url(prompt='consent')

            st.session_state.auth_url = auth_url
            
            # 修正箇所: st.query_params を使用
            query_params = st.query_params
            if 'code' in query_params:
                try:
                    flow.fetch_token(code=query_params['code'])
                    st.session_state.credentials = flow.credentials
                    st.session_state.logged_in = True
                    st.success("ログインしました！")
                    
                    # 修正箇所: st.query_params を使用してクエリパラメータをクリア
                    # st.query_params は辞書のように扱えるため、キーを指定して削除
                    del st.query_params['code'] # 'code' パラメータを削除
                    # 他の不要なクエリパラメータも削除する場合は同様に行う
                    # for param in list(st.query_params.keys()):
                    #    del st.query_params[param]

                    st.rerun()
                except Exception as e:
                    st.error(f"認証コードの処理中にエラーが発生しました: {e}")
                    st.session_state.logged_in = False
                    st.session_state.credentials = None
            else:
                st.sidebar.markdown(f'[Googleアカウントでログイン]({st.session_state.auth_url})', unsafe_allow_html=True)
                st.warning("ログインしてください。")
                st.stop()
    
    if st.session_state.logged_in and not st.session_state.user_info:
        try:
            oauth2_service = build('oauth2', 'v2', credentials=st.session_state.credentials)
            user_info = oauth2_service.userinfo().get().execute()
            st.session_state.user_info = user_info
            
            # 教員・生徒データ読み込み
            teachers_df = load_sheet_data(TEACHERS_SHEET_ID)
            students_df = load_sheet_data(STUDENTS_SHEET_ID)

            user_email = user_info['email']
            
            if not teachers_df.empty and user_email in teachers_df['email'].tolist():
                st.session_state.user_role = 'teacher'
                # 教員はすべての生徒の個別シートにアクセス可能
                st.session_state.associated_students_data = students_df[['student_name', 'individual_sheet_id']].to_dict(orient='records')
            elif not students_df.empty and user_email in students_df['parent_email'].tolist():
                st.session_state.user_role = 'parent'
                st.session_state.associated_students_data = students_df[
                    students_df['parent_email'] == user_email
                ][['student_name', 'individual_sheet_id']].to_dict(orient='records')
                
                if not st.session_state.associated_students_data:
                    st.error("あなたのメールアドレスに紐付けられた生徒が見つかりません。学校にお問い合わせください。")
                    st.session_state.logged_in = False
                    st.stop()
            else:
                st.error("あなたのメールアドレスは登録されていません。学校にお問い合わせください。")
                st.session_state.logged_in = False
                st.stop()
                
        except Exception as e:
            st.error(f"ユーザー情報の取得または役割判定中にエラーが発生しました: {e}")
            st.session_state.logged_in = False
            st.session_state.credentials = None
            st.session_state.user_info = None
            st.session_state.user_role = None
            st.session_state.associated_students_data = []
            st.stop()

    return st.session_state.credentials if st.session_state.logged_in else None

# --- Streamlitアプリ本体 ---
def main():
    st.set_page_config(layout="wide", page_title="デジタル連絡帳")
    st.title("🌟 特別支援学校向け デジタル連絡帳")
    st.markdown("---")

    credentials = authenticate_google_oauth()

    if st.session_state.logged_in and credentials:
        user_name = st.session_state.user_info.get('name', st.session_state.user_info['email'])
        user_role = st.session_state.user_role
        associated_students_data = st.session_state.associated_students_data
        student_names_only = [s['student_name'] for s in associated_students_data]

        st.sidebar.success(f"ようこそ、{user_name}さん！ ({'教員' if user_role == 'teacher' else '保護者'})")
        if st.sidebar.button("ログアウト"):
            st.session_state.logged_in = False
            st.session_state.credentials = None
            st.session_state.user_info = None
            st.session_state.user_role = None
            st.session_state.associated_students_data = []
            # 修正箇所: st.query_params を使用してクエリパラメータをクリア
            for param in list(st.query_params.keys()):
                del st.query_params[param]
            st.rerun()

        st.sidebar.header("ナビゲーション")

        # --- 各種データの読み込み ---
        # 教員リストと生徒リストは認証時に読み込まれるため、ここでは不要。
        # 支援メモとカレンダーはここで読み込む
        support_memos_df = load_sheet_data(SUPPORT_MEMO_SHEET_ID)
        calendar_df = load_sheet_data(CALENDAR_SHEET_ID)


        # --- 教員画面 ---
        if user_role == 'teacher':
            st.sidebar.subheader("教員メニュー")
            menu_selection = st.sidebar.radio(
                "機能を選択",
                ["個別連絡作成", "全体連絡作成", "連絡帳一覧", "生徒別支援メモ", "カレンダー", "ダッシュボード"]
            )
            
            # 生徒選択コンポーネント
            student_options = ["全体"] + student_names_only
            selected_student_name = st.sidebar.selectbox("対象生徒を選択", student_options, key="teacher_student_select")
            
            # 選択された生徒の個別シートIDを特定
            selected_student_sheet_id = None
            if selected_student_name != "全体":
                for student_data in associated_students_data:
                    if student_data['student_name'] == selected_student_name:
                        selected_student_sheet_id = student_data['individual_sheet_id']
                        break
                if selected_student_sheet_id is None:
                    st.error(f"生徒 '{selected_student_name}' の個別連絡シートIDが見つかりません。")
                    st.stop()

            if menu_selection == "個別連絡作成":
                if selected_student_name == "全体":
                    st.warning("個別連絡作成では「全体」を選択できません。特定の生徒を選択してください。")
                elif selected_student_sheet_id:
                    st.header(f"個別連絡作成: {selected_student_name} 宛")
                    with st.form("individual_contact_form", clear_on_submit=True):
                        contact_date = st.date_input("連絡対象日付", datetime.now().date())
                        school_message = st.text_area("学校からの連絡内容", height=150, placeholder="今日の様子や、伝えたいことを入力してください。")
                        items_notice = st.text_input("持ち物・特記事項", placeholder="明日の持ち物など、特記事項があれば入力してください。")
                        remarks = st.text_area("備考（教員用、必要であれば）", placeholder="保護者には表示されません。", help="内部メモとして利用できます。")
                        uploaded_file = st.file_uploader("画像を添付 (任意)", type=["png", "jpg", "jpeg", "gif", "pdf"])

                        submitted = st.form_submit_button("個別連絡を送信")
                        if submitted:
                            if not school_message.strip():
                                st.error("連絡内容は必須です。")
                            else:
                                image_url = ""
                                if uploaded_file:
                                    with st.spinner("画像をGoogle Driveにアップロード中..."):
                                        image_url = upload_to_drive(uploaded_file, uploaded_file.name, uploaded_file.type, credentials)
                                if image_url is None:
                                    st.error("画像アップロードに失敗しました。再度お試しください。")
                                else:
                                    new_record = {
                                        "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                        "date": contact_date.strftime("%Y/%m/%d"),
                                        "sender": user_name,
                                        "message": school_message, # 'school_message' -> 'message' に変更
                                        "home_reply": "",
                                        "items_notice": items_notice,
                                        "remarks": remarks,
                                        "image_url": image_url,
                                        "read_status": "未読"
                                    }
                                    if append_row_to_sheet(selected_student_sheet_id, new_record):
                                        st.success(f"個別連絡を {selected_student_name} に送信しました！")
                                        st.balloons()
                                    else:
                                        st.error("個別連絡の送信に失敗しました。")

            elif menu_selection == "全体連絡作成":
                st.header("全体連絡作成")
                with st.form("general_contact_form", clear_on_submit=True):
                    contact_date = st.date_input("連絡対象日付", datetime.now().date())
                    school_message = st.text_area("全体への連絡内容", height=200, placeholder="全体へのお知らせや共有事項を入力してください。")
                    items_notice = st.text_input("持ち物・特記事項", placeholder="全体への持ち物など、特記事項があれば入力してください。") # 全体連絡にも持ち物欄を追加
                    uploaded_file = st.file_uploader("画像を添付 (任意)", type=["png", "jpg", "jpeg", "gif", "pdf"])

                    submitted = st.form_submit_button("全体連絡を送信")
                    if submitted:
                        if not school_message.strip():
                            st.error("連絡内容は必須です。")
                        else:
                            image_url = ""
                            if uploaded_file:
                                with st.spinner("画像をGoogle Driveにアップロード中..."):
                                    image_url = upload_to_drive(uploaded_file, uploaded_file.name, uploaded_file.type, credentials)
                            if image_url is None:
                                st.error("画像アップロードに失敗しました。再度お試しください。")
                            else:
                                new_record = {
                                    "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                    "date": contact_date.strftime("%Y/%m/%d"),
                                    "sender": user_name,
                                    "message": school_message,
                                    "items_notice": items_notice, # 全体連絡にも持ち物欄を追加
                                    "image_url": image_url
                                }
                                if append_row_to_sheet(GENERAL_CONTACTS_SHEET_ID, new_record):
                                    st.success("全体連絡を送信しました！")
                                    st.balloons()
                                else:
                                    st.error("全体連絡の送信に失敗しました。")

            elif menu_selection == "連絡帳一覧":
                st.header("連絡帳一覧と既読確認")
                
                # フィルタリング
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    contact_type_filter = st.selectbox("連絡種別で絞り込み", ["すべて", "全体連絡", "個別連絡"])
                with filter_col2:
                    read_filter = st.selectbox("既読状況で絞り込み (個別連絡のみ)", ["すべて", "既読", "未読"])

                search_query = st.text_input("キーワード検索", placeholder="連絡内容、備考などで検索...")
                
                # 全体連絡を表示
                st.subheader("📢 全体連絡")
                general_df = load_sheet_data(GENERAL_CONTACTS_SHEET_ID)
                if not general_df.empty:
                    general_df["timestamp"] = pd.to_datetime(general_df["timestamp"])
                    general_df = general_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)
                    
                    if search_query:
                        general_df = general_df[
                            general_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                        ]
                    
                    if contact_type_filter in ["すべて", "全体連絡"]:
                        if not general_df.empty:
                            for index, row in general_df.iterrows():
                                with st.expander(f"📅 {row['date']} - {row['sender']} (全体連絡)", expanded=False):
                                    st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                                    st.info(f"**連絡内容:** {row['message']}")
                                    if row['items_notice']:
                                        st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                                    if row['image_url']:
                                        if row['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                            st.image(row['image_url'], caption="添付画像", width=300)
                                        elif row['image_url'].lower().endswith(('.pdf')):
                                            st.markdown(f"**添付PDF:** [こちらをクリックして閲覧]({row['image_url']})")
                                        else:
                                            st.markdown(f"**添付ファイル:** [ファイルリンク]({row['image_url']})")
                                    st.markdown("---")
                        else:
                            st.info("全体連絡はまだありません。")
                else:
                    st.info("全体連絡データが読み込めませんでした。")

                # 個別連絡を表示
                st.subheader("🧑‍🏫 個別連絡")
                if contact_type_filter in ["すべて", "個別連絡"]:
                    for student_data in associated_students_data:
                        student_name = student_data['student_name']
                        individual_sheet_id = student_data['individual_sheet_id']

                        st.markdown(f"##### {student_name} の連絡")
                        individual_df = load_sheet_data(individual_sheet_id)
                        if not individual_df.empty:
                            individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"])
                            if 'read_status' not in individual_df.columns:
                                individual_df['read_status'] = '未読' # 新しい列を追加して既存データに対応
                            individual_df = individual_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                            display_individual_df = individual_df.copy()
                            if read_filter != "すべて":
                                display_individual_df = display_individual_df[display_individual_df["read_status"] == read_filter]
                            if search_query:
                                display_individual_df = display_individual_df[
                                    display_individual_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                                ]

                            if not display_individual_df.empty:
                                for index, row in display_individual_df.iterrows():
                                    with st.expander(f"📅 {row['date']} - {row['sender']} ({row['read_status']})", expanded=False):
                                        st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                                        st.info(f"**学校からの連絡:** {row['message']}") # 'school_message' -> 'message'
                                        if row['home_reply']:
                                            st.success(f"**家庭からの返信:** {row['home_reply']}")
                                        if row['items_notice']:
                                            st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                                        if row['remarks']:
                                            st.caption(f"**備考:** {row['remarks']}")
                                        if row['image_url']:
                                            if row['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                                st.image(row['image_url'], caption="添付画像", width=300)
                                            elif row['image_url'].lower().endswith(('.pdf')):
                                                st.markdown(f"**添付PDF:** [こちらをクリックして閲覧]({row['image_url']})")
                                            else:
                                                st.markdown(f"**添付ファイル:** [ファイルリンク]({row['image_url']})")

                                        # 既読/未読ステータス更新機能 (教員のみ)
                                        current_read_status = row['read_status']
                                        new_read_status = st.radio(
                                            f"既読ステータスを更新 (生徒: {student_name}, ID: {index})",
                                            ["未読", "既読"],
                                            index=0 if current_read_status == "未読" else 1,
                                            key=f"read_status_radio_{student_name}_{index}"
                                        )
                                        if new_read_status != current_read_status:
                                            sheet_row_index = individual_df.index[individual_df['timestamp'] == row['timestamp']].tolist()[0] + 2
                                            if update_row_in_sheet(individual_sheet_id, sheet_row_index, {"read_status": new_read_status}):
                                                st.success(f"{student_name} の既読ステータスを '{new_read_status}' に更新しました。")
                                                st.rerun()
                                            else:
                                                st.error("既読ステータスの更新に失敗しました。")
                            else:
                                st.info(f"{student_name} の個別連絡はまだありません。")
                        else:
                            st.info(f"{student_name} の個別連絡データが読み込めませんでした。シート設定を確認してください。")
                        st.markdown("---")
                
            elif menu_selection == "生徒別支援メモ":
                st.header(f"{selected_student_name} 支援メモ (教員専用)")
                st.info("このメモは保護者には公開されません。")

                if selected_student_name == "全体":
                    st.warning("「全体」の支援メモは作成できません。特定の生徒を選択してください。")
                else:
                    current_memo = support_memos_df[support_memos_df['student_name'] == selected_student_name]['memo_content'].iloc[0] if not support_memos_df.empty and selected_student_name in support_memos_df['student_name'].tolist() else ""

                    with st.form(key=f"support_memo_form_{selected_student_name}", clear_on_submit=False):
                        new_memo_content = st.text_area(f"{selected_student_name}の支援メモを入力してください", value=current_memo, height=250)
                        
                        submitted_memo = st.form_submit_button("メモを保存")
                        if submitted_memo:
                            if not support_memos_df.empty and selected_student_name in support_memos_df['student_name'].tolist():
                                sheet_row_index = support_memos_df.index[support_memos_df['student_name'] == selected_student_name].tolist()[0] + 2
                                if update_row_in_sheet(SUPPORT_MEMO_SHEET_ID, sheet_row_index, {"memo_content": new_memo_content, "last_updated": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}):
                                    st.success("支援メモを更新しました。")
                                else:
                                    st.error("支援メモの更新に失敗しました。")
                            else:
                                new_memo_record = {
                                    "student_name": selected_student_name,
                                    "memo_content": new_memo_content,
                                    "created_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                    "last_updated": datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                                }
                                if append_row_to_sheet(SUPPORT_MEMO_SHEET_ID, new_memo_record):
                                    st.success("支援メモを保存しました。")
                                else:
                                    st.error("支援メモの保存に失敗しました。")
                            st.cache_data.clear()
                            st.rerun()
                    
            elif menu_selection == "カレンダー":
                st.header("カレンダー (行事予定・配布物)")
                if not calendar_df.empty:
                    calendar_df['event_date'] = pd.to_datetime(calendar_df['event_date'], errors='coerce')
                    calendar_df = calendar_df.dropna(subset=['event_date'])
                    calendar_df = calendar_df.sort_values(by='event_date')

                    st.subheader("今後の予定")
                    today = datetime.now().date()
                    upcoming_events = calendar_df[calendar_df['event_date'].dt.date >= today]
                    
                    if not upcoming_events.empty:
                        for index, event in upcoming_events.iterrows():
                            st.markdown(f"**{event['event_date'].strftime('%Y/%m/%d')}**: **{event['event_name']}** - {event['description']}")
                            if event['attachment_url']:
                                st.markdown(f"添付資料: [こちら]({event['attachment_url']})")
                            st.markdown("---")
                    else:
                        st.info("今後のイベントはありません。")
                    
                    st.subheader("新規イベント追加")
                    with st.form("add_event_form", clear_on_submit=True):
                        event_date = st.date_input("日付", datetime.now().date())
                        event_name = st.text_input("イベント名")
                        description = st.text_area("説明")
                        event_attachment = st.file_uploader("添付ファイル (任意)", type=["pdf", "jpg", "png"])
                        
                        submitted_event = st.form_submit_button("イベントを追加")
                        if submitted_event:
                            if not event_name.strip():
                                st.error("イベント名は必須です。")
                            else:
                                attachment_url = ""
                                if event_attachment:
                                    with st.spinner("ファイルをGoogle Driveにアップロード中..."):
                                        attachment_url = upload_to_drive(event_attachment, event_attachment.name, event_attachment.type, credentials)
                                if attachment_url is None:
                                    st.error("ファイルアップロードに失敗しました。")
                                else:
                                    new_event = {
                                        "event_date": event_date.strftime("%Y/%m/%d"),
                                        "event_name": event_name,
                                        "description": description,
                                        "attachment_url": attachment_url
                                    }
                                    if append_row_to_sheet(CALENDAR_SHEET_ID, new_event):
                                        st.success("イベントを追加しました！")
                                        st.rerun()
                                    else:
                                        st.error("イベントの追加に失敗しました。")
                else:
                    st.info("カレンダーデータが読み込めませんでした。シート設定を確認してください。")

            elif menu_selection == "ダッシュボード":
                st.header("ダッシュボード")
                
                # 全体連絡のデータ
                general_df = load_sheet_data(GENERAL_CONTACTS_SHEET_ID)
                general_contacts_count = len(general_df) if not general_df.empty else 0

                # 個別連絡のデータ集計
                total_individual_contacts = 0
                total_read_individual = 0
                total_unread_individual = 0
                total_replied_individual = 0

                for student_data in associated_students_data:
                    individual_sheet_id = student_data['individual_sheet_id']
                    individual_df = load_sheet_data(individual_sheet_id)
                    if not individual_df.empty:
                        total_individual_contacts += len(individual_df)
                        if 'read_status' in individual_df.columns:
                            total_read_individual += (individual_df['read_status'] == '既読').sum()
                            total_unread_individual += (individual_df['read_status'] == '未読').sum()
                        total_replied_individual += (individual_df['home_reply'].astype(str).str.strip() != '').sum()
                
                st.subheader("連絡件数概要")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("全体連絡数", general_contacts_count)
                col2.metric("個別連絡数", total_individual_contacts)
                col3.metric("個別連絡 (既読)", total_read_individual)
                col4.metric("個別連絡 (未読)", total_unread_individual)

                st.subheader("月別連絡数 (個別連絡)")
                all_individual_contacts_df = pd.DataFrame()
                for student_data in associated_students_data:
                    individual_sheet_id = student_data['individual_sheet_id']
                    individual_df = load_sheet_data(individual_sheet_id)
                    if not individual_df.empty:
                        all_individual_contacts_df = pd.concat([all_individual_contacts_df, individual_df])
                
                if not all_individual_contacts_df.empty:
                    all_individual_contacts_df["timestamp"] = pd.to_datetime(all_individual_contacts_df["timestamp"])
                    all_individual_contacts_df["month"] = all_individual_contacts_df["timestamp"].dt.to_period("M")
                    monthly_counts = all_individual_contacts_df["month"].value_counts().sort_index()
                    st.bar_chart(monthly_counts)
                else:
                    st.info("個別連絡データがありません。")

        # --- 保護者画面 ---
        elif user_role == 'parent':
            st.sidebar.subheader("保護者メニュー")
            menu_selection = st.sidebar.radio(
                "機能を選択",
                ["自分の連絡帳", "返信作成", "カレンダー"]
            )
            
            # 保護者の場合、関連する生徒を選択
            if len(associated_students_data) > 1:
                selected_student_name = st.sidebar.selectbox("お子さんを選択", student_names_only, key="parent_student_select")
            elif associated_students_data:
                selected_student_name = student_names_only[0]
                st.sidebar.info(f"連絡帳: {selected_student_name}")
            else:
                st.error("紐付けられた生徒情報がありません。")
                st.stop()

            # 選択された生徒の個別シートIDを特定
            selected_student_sheet_id = None
            if selected_student_name:
                for student_data in associated_students_data:
                    if student_data['student_name'] == selected_student_name:
                        selected_student_sheet_id = student_data['individual_sheet_id']
                        break
            if selected_student_sheet_id is None:
                st.error(f"生徒 '{selected_student_name}' の個別連絡シートIDが見つかりません。")
                st.stop()


            if menu_selection == "自分の連絡帳":
                st.header(f"{selected_student_name} 連絡帳")
                
                # 全体連絡を表示
                st.subheader("📢 全体連絡")
                general_df = load_sheet_data(GENERAL_CONTACTS_SHEET_ID)
                if not general_df.empty:
                    general_df["timestamp"] = pd.to_datetime(general_df["timestamp"])
                    general_df = general_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)
                    
                    for index, row in general_df.iterrows():
                        with st.expander(f"📅 {row['date']} - {row['sender']} (全体連絡)", expanded=False):
                            st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                            st.info(f"**連絡内容:** {row['message']}")
                            if row['items_notice']:
                                st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                            if row['image_url']:
                                if row['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    st.image(row['image_url'], caption="添付画像", width=300)
                                elif row['image_url'].lower().endswith(('.pdf')):
                                    st.markdown(f"**添付PDF:** [こちらをクリックして閲覧]({row['image_url']})")
                                else:
                                    st.markdown(f"**添付ファイル:** [ファイルリンク]({row['image_url']})")
                            st.markdown("---")
                else:
                    st.info("全体連絡はまだありません。")

                # 個別連絡を表示
                st.subheader(f"🧑‍🏫 {selected_student_name} への個別連絡")
                individual_df = load_sheet_data(selected_student_sheet_id)
                if not individual_df.empty:
                    individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"])
                    if 'read_status' not in individual_df.columns:
                        individual_df['read_status'] = '未読'
                    individual_df = individual_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                    for index, row in individual_df.iterrows():
                        with st.expander(f"📅 {row['date']} - {row['sender']} ({row['read_status']})", expanded=False):
                            st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                            st.info(f"**学校からの連絡:** {row['message']}")
                            if row['home_reply']:
                                st.success(f"**あなたの返信:** {row['home_reply']}")
                            if row['items_notice']:
                                st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                            if row['image_url']:
                                if row['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    st.image(row['image_url'], caption="添付画像", width=300)
                                elif row['image_url'].lower().endswith(('.pdf')):
                                    st.markdown(f"**添付PDF:** [こちらをクリックして閲覧]({row['image_url']})")
                                else:
                                    st.markdown(f"**添付ファイル:** [ファイルリンク]({row['image_url']})")
                            
                            # 保護者が閲覧した際に「既読」にするロジック
                            if row['read_status'] == '未読':
                                if f"mark_read_{selected_student_name}_{index}" not in st.session_state:
                                    st.session_state[f"mark_read_{selected_student_name}_{index}"] = False

                                if not st.session_state[f"mark_read_{selected_student_name}_{index}"]:
                                    st.info("この連絡はまだ既読になっていません。")
                                    if st.button("既読にする", key=f"read_button_{selected_student_name}_{index}"):
                                        sheet_row_index = individual_df.index[individual_df['timestamp'] == row['timestamp']].tolist()[0] + 2
                                        if update_row_in_sheet(selected_student_sheet_id, sheet_row_index, {"read_status": "既読"}):
                                            st.session_state[f"mark_read_{selected_student_name}_{index}"] = True
                                            st.success("連絡を既読にしました。")
                                            st.rerun()
                                        else:
                                            st.error("既読ステータスの更新に失敗しました。")
                        st.markdown("---")
                else:
                    st.info(f"{selected_student_name} への個別連絡はまだありません。")

            elif menu_selection == "返信作成":
                st.header(f"{selected_student_name} からの返信作成")
                st.info("返信したい個別連絡を選択してください。")

                individual_df = load_sheet_data(selected_student_sheet_id)
                if not individual_df.empty:
                    reply_needed_df = individual_df[
                        (individual_df["home_reply"].astype(str).str.strip() == "")
                    ]

                    if not reply_needed_df.empty:
                        latest_unreplied = reply_needed_df.iloc[0]
                        
                        st.subheader(f"返信対象連絡: {latest_unreplied['date']} の学校からの連絡")
                        st.info(latest_unreplied['message'])
                        if latest_unreplied['image_url']:
                            if latest_unreplied['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                st.image(latest_unreplied['image_url'], caption="添付画像", width=300)
                            elif latest_unreplied['image_url'].lower().endswith(('.pdf')):
                                st.markdown(f"添付PDF: [こちらをクリックして閲覧]({latest_unreplied['image_url']})")

                        with st.form("reply_form", clear_on_submit=True):
                            home_reply = st.text_area("学校への返信内容", height=150, placeholder="先生への返信を入力してください。")
                            uploaded_file_reply = st.file_uploader("画像を添付 (任意)", type=["png", "jpg", "jpeg", "gif", "pdf"])

                            submitted_reply = st.form_submit_button("返信を送信")
                            if submitted_reply:
                                if not home_reply.strip():
                                    st.error("返信内容は必須です。")
                                else:
                                    image_url_reply = ""
                                    if uploaded_file_reply:
                                        with st.spinner("画像をGoogle Driveにアップロード中..."):
                                            image_url_reply = upload_to_drive(uploaded_file_reply, uploaded_file_reply.name, uploaded_file_reply.type, credentials)
                                    if image_url_reply is None:
                                        st.error("画像アップロードに失敗しました。再度お試しください。")
                                    else:
                                        sheet_row_index = individual_df.index[individual_df['timestamp'] == latest_unreplied['timestamp']].tolist()[0] + 2
                                        data_to_update = {"home_reply": home_reply}
                                        if image_url_reply:
                                            data_to_update["image_url"] = image_url_reply
                                        
                                        if update_row_in_sheet(selected_student_sheet_id, sheet_row_index, data_to_update):
                                            st.success("返信を送信しました！")
                                            st.balloons()
                                            st.rerun()
                                        else:
                                            st.error("返信の保存に失敗しました。")
                    else:
                        st.info("返信する未返信の個別連絡はありません。")
                else:
                    st.info("個別連絡データがありません。")
            
            elif menu_selection == "カレンダー":
                st.header("カレンダー (行事予定・配布物)")
                if not calendar_df.empty:
                    calendar_df['event_date'] = pd.to_datetime(calendar_df['event_date'], errors='coerce')
                    calendar_df = calendar_df.dropna(subset=['event_date'])
                    calendar_df = calendar_df.sort_values(by='event_date')

                    st.subheader("今後の予定")
                    today = datetime.now().date()
                    upcoming_events = calendar_df[calendar_df['event_date'].dt.date >= today]
                    
                    if not upcoming_events.empty:
                        for index, event in upcoming_events.iterrows():
                            st.markdown(f"**{event['event_date'].strftime('%Y/%m/%d')}**: **{event['event_name']}** - {event['description']}")
                            if event['attachment_url']:
                                st.markdown(f"添付資料: [こちら]({event['attachment_url']})")
                            st.markdown("---")
                    else:
                        st.info("今後のイベントはありません。")
                else:
                    st.info("カレンダーデータが読み込めませんでした。")


    else:
        st.info("サイドバーからGoogleアカウントでログインしてください。")
        st.image("https://www.gstatic.com/images/branding/product/2x/google_g_48dp.png")
        st.markdown("デジタル連絡帳へようこそ！")
        st.markdown("このアプリは、特別支援学校の先生と保護者の皆様が、安全かつ効率的に連絡を取り合うためのツールです。")
        st.markdown("---")
        st.write("主な機能:")
        st.markdown("- 学校と家庭間の連絡をオンラインで完結")
        st.markdown("- 画像付きで視覚的にわかりやすい連絡が可能")
        st.markdown("- 過去のやり取りを自動保存し、振り返りや支援記録にも活用可能")
        
        st.image("https://raw.githubusercontent.com/streamlit/docs/main/docs/media/app_image_generation.png")
        
if __name__ == "__main__":
    main()