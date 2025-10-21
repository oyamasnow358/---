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
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

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

# NEW: プライバシーポリシーと利用規約のURLを定数として追加
PRIVACY_POLICY_URL = "https://docs.google.com/document/d/1uJX0GOorVXEutA7IKJOyBG6tZrLDesE7y_zAZGbSsKg/edit?tab=t.0"
TERMS_OF_SERVICE_URL = "https://docs.google.com/document/d/171oLSgxk55KCZhdTSJf0R3ibTWoIQPPrlQvz8EgAA0s/edit?tab=t.0"

# アプリケーション設定（シート名を読み込むように変更）
GENERAL_CONTACTS_SHEET_NAME = st.secrets["app_settings"]["general_contacts_sheet_name"]
STUDENTS_SHEET_NAME = st.secrets["app_settings"]["students_sheet_name"]
TEACHERS_SHEET_NAME = st.secrets["app_settings"]["teachers_sheet_name"]
SUPPORT_MEMO_SHEET_NAME = st.secrets["app_settings"]["support_memo_sheet_name"]
CALENDAR_SHEET_NAME = st.secrets["app_settings"]["calendar_sheet_name"]
DRIVE_FOLDER_ID = st.secrets["app_settings"]["drive_folder_id"]

# NEW: 教師シートのクラス列名を設定
TEACHER_CLASS_COLUMN = st.secrets["app_settings"]["teacher_class_column"] # 例: "class_name"
# NEW: 生徒シートのクラス列名を設定
STUDENT_CLASS_COLUMN = st.secrets["app_settings"]["student_class_column"] # 例: "class_name"

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
    st.session_state.associated_students_data = [] # {student_name: "", individual_sheet_name: "", class_name: ""}
if 'teacher_classes' not in st.session_state: # NEW: 教員の担当クラスを格納
    st.session_state.teacher_classes = []
# NEW: 既読ボタンのクリック状態を管理するセッションステートを追加
if 'read_button_clicked' not in st.session_state:
    st.session_state.read_button_clicked = {}


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
        st.exception(e) # 詳細なエラー情報を表示
        return None

# load_sheet_data関数をIDと名前の両方に対応できるように修正
# NEW: TTLを短くしすぎないように注意。デフォルトで60秒なので、短時間で複数回読み込む必要がある場合は適宜調整。
# エラー回避のため、キャッシュのクリアは明示的に行う箇所を減らします。
@st.cache_data(ttl=300) # 5分間に変更 (シートデータが頻繁に更新されないと仮定)
def load_sheet_data(identifier, identifier_type="id", worksheet_name="シート1"):
    """Googleスプレッドシートから指定シートのデータを読み込む (IDまたは名前で指定)"""
    gc = get_gspread_client()
    if gc is None:
        st.error(f"スプレッドシート '{identifier}' の読み込みに失敗しました: Gspreadクライアントが利用できません。")
        return pd.DataFrame()
    try:
        if identifier_type == "id":
            spreadsheet = gc.open_by_id(identifier)
        elif identifier_type == "name":
            spreadsheet = gc.open(identifier)
        else:
            st.error("無効なidentifier_typeが指定されました。'id' または 'name' を使用してください。")
            return pd.DataFrame()

        worksheet = spreadsheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.warning(f"スプレッドシート '{identifier}' 内のシート '{worksheet_name}' が見つかりません。シート名を確認してください。")
        return pd.DataFrame()
    except gspread.exceptions.SpreadsheetNotFound:
        st.warning(f"スプレッドシート '{identifier}' が見つかりませんでした。名前またはIDを確認してください。サービスアカウントに権限があるか確認してください。")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"スプレッドシート '{identifier}' の読み込み中にエラーが発生しました: {e}")
        st.exception(e)
        return pd.DataFrame()

# append_row_to_sheet関数をIDと名前の両方に対応できるように修正
def append_row_to_sheet(identifier, new_record, identifier_type="id", worksheet_name="シート1"):
    """Googleスプレッドシートにデータを追加する (IDまたは名前で指定)"""
    gc = get_gspread_client()
    if gc is None:
        return False
    try:
        if identifier_type == "id":
            spreadsheet = gc.open_by_id(identifier)
        elif identifier_type == "name":
            spreadsheet = gc.open(identifier)
        else:
            st.error("無効なidentifier_typeが指定されました。'id' または 'name' を使用してください。")
            return False

        worksheet = spreadsheet.worksheet(worksheet_name)
        header = worksheet.row_values(1)
        ordered_record = [new_record.get(col, '') for col in header]
        worksheet.append_row(ordered_record)
        # NEW: データ追加時は関連するキャッシュのみクリア
        st.cache_data.clear(hash_funcs={load_sheet_data: lambda _identifier, _type, _ws_name: (_identifier, _type, _ws_name)})
        # 具体的なシートのキャッシュをクリアする関数を定義 (load_sheet_dataのハッシュ関数と合わせる)
        # gc.open(identifier)のキャッシュはクリアされないため、シート全体を再取得する
        # より良いのは、特定のシートのデータだけをクリアするカスタムキャッシュを実装することですが、
        # ここでは一番影響の大きい load_sheet_data のキャッシュをクリアします
        st.cache_data.clear() # 全てのcache_dataをクリアすることで確実性を高めます。
        return True
    except Exception as e:
        st.error(f"スプレッドシート '{identifier}' へのデータ追加中にエラーが発生しました: {e}")
        st.exception(e)
        return False

# update_row_in_sheet関数をIDと名前の両方に対応できるように修正
def update_row_in_sheet(identifier, row_index, data_to_update, identifier_type="id", worksheet_name="シート1"):
    """Googleスプレッドシートの指定行を更新する (IDまたは名前で指定)"""
    gc = get_gspread_client()
    if gc is None:
        return False
    try:
        if identifier_type == "id":
            spreadsheet = gc.open_by_id(identifier)
        elif identifier_type == "name":
            spreadsheet = gc.open(identifier)
        else:
            st.error("無効なidentifier_typeが指定されました。'id' または 'name' を使用してください。")
            return False

        worksheet = spreadsheet.worksheet(worksheet_name)
        header = worksheet.row_values(1)
        for col_name, value in data_to_update.items():
            if col_name in header:
                col_index = header.index(col_name) + 1 # gspreadは1-indexed
                worksheet.update_cell(row_index, col_index, value)
        # NEW: データ更新時は関連するキャッシュのみクリア
        st.cache_data.clear() # 全てのcache_dataをクリアすることで確実性を高めます。
        return True
    except Exception as e:
        st.error(f"スプレッドシート '{identifier}' の行更新中にエラーが発生しました: {e}")
        st.exception(e)
        return False

# upload_to_drive関数を修正
def upload_to_drive(file_obj, file_name, mime_type, credentials):
    """Google Driveにファイルをアップロードし、共有可能なURLを返す"""
    try:
        drive_service = build('drive', 'v3', credentials=credentials)
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload( # MediaIoBaseUpload を使用
            file_obj, 
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
        st.exception(e)
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
                st.exception(e)
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
            
            query_params = st.query_params
            if 'code' in query_params:
                try:
                    flow.fetch_token(code=query_params['code'])
                    st.session_state.credentials = flow.credentials
                    st.session_state.logged_in = True
                    st.success("ログインしました！")
                    
                    st.rerun() # クエリパラメータをクリアするために rerunning
                except Exception as e:
                    st.error(f"認証コードの処理中にエラーが発生しました: {e}")
                    st.exception(e)
                    st.session_state.logged_in = False
                    st.session_state.credentials = None
            else:
                st.sidebar.markdown(f'[Googleアカウントでログイン]({st.session_state.auth_url})', unsafe_allow_html=True)
                # NEW: プライバシーポリシーと利用規約のリンクをログインボタンの下に追加
                st.sidebar.markdown(f'[プライバシーポリシー]({PRIVACY_POLICY_URL})', unsafe_allow_html=True)
                st.sidebar.markdown(f'[利用規約]({TERMS_OF_SERVICE_URL})', unsafe_allow_html=True)
                st.warning("ログインしてください。")
                st.stop()
    
    if st.session_state.logged_in and not st.session_state.user_info:
        try:
            oauth2_service = build('oauth2', 'v2', credentials=st.session_state.credentials)
            user_info = oauth2_service.userinfo().get().execute()
            st.session_state.user_info = user_info
            
            # 教員・生徒データ読み込み (シート名で指定)
            # NEW: ログイン時にのみこれらのデータを読み込む
            teachers_df = load_sheet_data(TEACHERS_SHEET_NAME, identifier_type="name")
            students_df = load_sheet_data(STUDENTS_SHEET_NAME, identifier_type="name")

            if teachers_df.empty or students_df.empty:
                st.error("教師または生徒のスプレッドシートが読み込めませんでした。サービスアカウントの権限、シート名、シート内シート名（'シート1'）を確認してください。")
                st.session_state.logged_in = False
                st.stop()

            user_email = user_info['email']
            
            if not teachers_df.empty and user_email in teachers_df['email'].tolist():
                st.session_state.user_role = 'teacher'
                # NEW: 教師の担当クラスを取得
                teacher_row = teachers_df[teachers_df['email'] == user_email].iloc[0]
                if TEACHER_CLASS_COLUMN in teacher_row:
                    # 複数のクラスを担当する場合に備え、カンマ区切りでリストに変換
                    # 空白を除外し、trimする
                    teacher_classes_raw = str(teacher_row[TEACHER_CLASS_COLUMN]).split(',')
                    st.session_state.teacher_classes = [c.strip() for c in teacher_classes_raw if c.strip()]
                    st.sidebar.info(f"担当クラス: {', '.join(st.session_state.teacher_classes)}") # デバッグ表示
                else:
                    st.warning(f"教師シートに '{TEACHER_CLASS_COLUMN}' 列が見つかりません。全生徒が表示されます。")
                    # 全ての生徒のクラスを収集し、重複を排除
                    all_classes = students_df[STUDENT_CLASS_COLUMN].dropna().unique().tolist()
                    st.session_state.teacher_classes = all_classes # 全クラス対象とする

                # individual_sheet_name と class_name を生徒データに含める
                if 'individual_sheet_name' in students_df.columns and STUDENT_CLASS_COLUMN in students_df.columns:
                    # NEW: 担当クラスの生徒のみに絞り込む
                    if not st.session_state.teacher_classes: # teacher_classesが空の場合（全生徒対象と見なす）
                        st.session_state.associated_students_data = students_df[
                            ['student_name', 'individual_sheet_name', STUDENT_CLASS_COLUMN]
                        ].to_dict(orient='records')
                    else: # 特定のクラスを担当する教師の場合
                        filtered_students_df = students_df[
                            students_df[STUDENT_CLASS_COLUMN].isin(st.session_state.teacher_classes)
                        ]
                        st.session_state.associated_students_data = filtered_students_df[
                            ['student_name', 'individual_sheet_name', STUDENT_CLASS_COLUMN]
                        ].to_dict(orient='records')
                        
                else:
                    st.error(f"生徒シートに 'individual_sheet_name' または '{STUDENT_CLASS_COLUMN}' 列が見つかりません。")
                    st.session_state.logged_in = False
                    st.stop()

            elif not students_df.empty and user_email in students_df['parent_email'].tolist():
                st.session_state.user_role = 'parent'
                if 'individual_sheet_name' in students_df.columns and STUDENT_CLASS_COLUMN in students_df.columns:
                    st.session_state.associated_students_data = students_df[
                        students_df['parent_email'] == user_email
                    ][['student_name', 'individual_sheet_name', STUDENT_CLASS_COLUMN]].to_dict(orient='records')
                else:
                    st.error(f"生徒シートに 'individual_sheet_name' または '{STUDENT_CLASS_COLUMN}' 列が見つかりません。")
                    st.session_state.logged_in = False
                    st.stop()
                
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
            st.exception(e)
            st.session_state.logged_in = False
            st.session_state.credentials = None
            st.session_state.user_info = None
            st.session_state.user_role = None
            st.session_state.associated_students_data = []
            st.session_state.teacher_classes = [] # NEW
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
        
        # NEW: ログインした教員・保護者に関連付けられた生徒データのみを使用
        associated_students_data = st.session_state.associated_students_data
        student_names_only = [s['student_name'] for s in associated_students_data]

        st.sidebar.success(f"ようこそ、{user_name}さん！ ({'教員' if user_role == 'teacher' else '保護者'})")
        if st.sidebar.button("ログアウト"):
            st.session_state.logged_in = False
            st.session_state.credentials = None
            st.session_state.user_info = None
            st.session_state.user_role = None
            st.session_state.associated_students_data = []
            st.session_state.teacher_classes = [] # NEW
            st.session_state.read_button_clicked = {} # NEW: 既読ボタンの状態もリセット
            # Streamlitのクエリパラメータをクリアして再実行
            st.experimental_set_query_params()
            st.rerun() # ログアウト時は確実なページ遷移のため reruning に変更
            # st.stop() はこの場合、ページの状態が完全にリセットされない可能性があるため、rerunが適切

        st.sidebar.header("ナビゲーション")

        # --- 教員画面 ---
        if user_role == 'teacher':
            st.sidebar.subheader("教員メニュー")
            menu_selection = st.sidebar.radio(
                "機能を選択",
                ["個別連絡作成", "全体連絡作成", "連絡帳一覧", "生徒別支援メモ", "カレンダー", "ダッシュボード"]
            )
            
            # NEW: 教員の場合は、自身の担当クラスの生徒と「全体」を選択肢として提示
            # student_options のリスト生成はここで
            student_options = ["全体"] + student_names_only
            selected_student_name = st.sidebar.selectbox("対象生徒を選択", student_options, key="teacher_student_select")
            
            # individual_sheet_id の代わりに individual_sheet_name を使用
            selected_individual_sheet_name = None 
            if selected_student_name != "全体":
                for student_data in associated_students_data:
                    if student_data['student_name'] == selected_student_name:
                        selected_individual_sheet_name = student_data['individual_sheet_name']
                        break
                if selected_individual_sheet_name is None:
                    st.error(f"生徒 '{selected_student_name}' の個別連絡シート名が見つかりません。生徒情報シートを確認してください。")
            
            # --- 各種データの読み込み ---
            # NEW: 必要なメニュー選択時のみデータを読み込む
            support_memos_df = pd.DataFrame()
            calendar_df_full = pd.DataFrame()
            if menu_selection == "生徒別支援メモ":
                support_memos_df = load_sheet_data(SUPPORT_MEMO_SHEET_NAME, identifier_type="name")
            if menu_selection == "カレンダー":
                calendar_df_full = load_sheet_data(CALENDAR_SHEET_NAME, identifier_type="name")
                # カレンダーデータフレームが空の場合、後続処理でKeyErrorとならないよう空のDFのスキーマを定義
                if calendar_df_full.empty:
                    st.warning("カレンダーデータが読み込めませんでした。シート名または権限を確認してください。")
                    calendar_df_full = pd.DataFrame(columns=['event_date', 'event_name', 'description', 'attachment_url', 'target_classes'])
                
                if 'target_classes' not in calendar_df_full.columns:
                    calendar_df_full['target_classes'] = '' # デフォルト値を設定
                
                if 'event_date' in calendar_df_full.columns:
                    calendar_df_full['event_date'] = pd.to_datetime(calendar_df_full['event_date'], format='%Y/%m/%d', errors='coerce')
                    calendar_df_full = calendar_df_full.dropna(subset=['event_date']) 
                else:
                    calendar_df_full = pd.DataFrame(columns=['event_date', 'event_name', 'description', 'attachment_url', 'target_classes'])

                if not calendar_df_full.empty and 'event_date' in calendar_df_full.columns:
                    calendar_df_full = calendar_df_full.sort_values(by='event_date')

            if menu_selection == "個別連絡作成":
                if selected_student_name == "全体":
                    st.warning("個別連絡作成では「全体」を選択できません。特定の生徒を選択してください。")
                elif selected_individual_sheet_name: 
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
                                        uploaded_file.seek(0) 
                                        image_url = upload_to_drive(uploaded_file, uploaded_file.name, uploaded_file.type, credentials)
                                    if image_url is None: 
                                        st.error("画像アップロードに失敗しました。再度お試しください。")
                                        # NEW: st.stop() の代わりに return を使用して処理を中断
                                        return 
                                        
                                new_record = {
                                    "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                    "date": contact_date.strftime("%Y/%m/%d"),
                                    "sender": user_name,
                                    "message": school_message,
                                    "home_reply": "",
                                    "items_notice": items_notice,
                                    "remarks": remarks,
                                    "image_url": image_url,
                                    "read_status": "未読" # NEW: read_statusを最初から設定
                                }
                                if append_row_to_sheet(selected_individual_sheet_name, new_record, identifier_type="name"):
                                    st.success(f"個別連絡を {selected_student_name} に送信しました！")
                                    st.balloons()
                                    st.rerun() # 送信後、表示を更新するためにrerun
                                else:
                                    st.error("個別連絡の送信に失敗しました。")
                else:
                    if selected_student_name != "全体":
                        st.info("生徒の個別連絡シート名が見つからないため、個別連絡を作成できません。") 

            elif menu_selection == "全体連絡作成":
                st.header("全体連絡作成")
                with st.form("general_contact_form", clear_on_submit=True):
                    contact_date = st.date_input("連絡対象日付", datetime.now().date())
                    school_message = st.text_area("全体への連絡内容", height=200, placeholder="全体へのお知らせや共有事項を入力してください。")
                    items_notice = st.text_input("持ち物・特記事項", placeholder="全体への持ち物など、特記事項があれば入力してください。")
                    uploaded_file = st.file_uploader("画像を添付 (任意)", type=["png", "jpg", "jpeg", "gif", "pdf"])

                    submitted = st.form_submit_button("全体連絡を送信")
                    if submitted:
                        if not school_message.strip():
                            st.error("連絡内容は必須です。")
                        else:
                            image_url = ""
                            if uploaded_file:
                                with st.spinner("画像をGoogle Driveにアップロード中..."):
                                    uploaded_file.seek(0) 
                                    image_url = upload_to_drive(uploaded_file, uploaded_file.name, uploaded_file.type, credentials)
                            if image_url is None: 
                                st.error("画像アップロードに失敗しました。再度お試しください。")
                                return 
                                
                            new_record = {
                                "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                "date": contact_date.strftime("%Y/%m/%d"),
                                "sender": user_name,
                                "message": school_message,
                                "items_notice": items_notice,
                                "image_url": image_url
                            }
                            if append_row_to_sheet(GENERAL_CONTACTS_SHEET_NAME, new_record, identifier_type="name"):
                                st.success("全体連絡を送信しました！")
                                st.balloons()
                                st.rerun() # 送信後、表示を更新するためにrerun
                            else:
                                st.error("全体連絡の送信に失敗しました。")

            elif menu_selection == "連絡帳一覧":
                st.header("連絡帳一覧と既読確認")
                
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    contact_type_filter = st.selectbox("連絡種別で絞り込み", ["すべて", "全体連絡", "個別連絡"])
                with filter_col2:
                    read_filter = st.selectbox("既読状況で絞り込み (個別連絡のみ)", ["すべて", "既読", "未読"])

                search_query = st.text_input("キーワード検索", placeholder="連絡内容、備考などで検索...")
                
                st.subheader("📢 全体連絡")
                # NEW: 全体連絡は一度だけ読み込む
                general_df = load_sheet_data(GENERAL_CONTACTS_SHEET_NAME, identifier_type="name") 
                if not general_df.empty:
                    general_df["timestamp"] = pd.to_datetime(general_df["timestamp"], errors='coerce') 
                    general_df = general_df.dropna(subset=['timestamp']) 
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

                st.subheader("🧑‍🏫 個別連絡")
                if contact_type_filter in ["すべて", "個別連絡"]:
                    for student_data in associated_students_data: 
                        student_name = student_data['student_name']
                        individual_sheet_name = student_data['individual_sheet_name']

                        st.markdown(f"##### {student_name} の連絡")
                        # NEW: 個別連絡も一度だけ読み込む
                        individual_df = load_sheet_data(individual_sheet_name, identifier_type="name")
                        if not individual_df.empty:
                            individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"], errors='coerce') 
                            individual_df = individual_df.dropna(subset=['timestamp']) 
                            # NEW: 'read_status' 列の存在チェックとデフォルト値の設定はデータフレーム読み込み後に一度だけ
                            if 'read_status' not in individual_df.columns:
                                individual_df['read_status'] = '未読' # スプレッドシートに列がない場合
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
                                    # unique key for expander
                                    expander_key = f"expander_{student_name}_{index}" 
                                    with st.expander(f"📅 {row['date']} - {row['sender']} ({row['read_status']})", expanded=False, key=expander_key):
                                        st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                                        st.info(f"**学校からの連絡:** {row['message']}")
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

                                        current_read_status = row['read_status']
                                        # NEW: ラジオボタンのキーもユニークにし、セッションステートで管理
                                        radio_key = f"read_status_radio_{student_name}_{index}"
                                        new_read_status = st.radio(
                                            f"既読ステータスを更新 (生徒: {student_name}, 日付: {row['date']})",
                                            ["未読", "既読"],
                                            index=0 if current_read_status == "未読" else 1,
                                            key=radio_key
                                        )
                                        if new_read_status != current_read_status:
                                            # display_individual_df のインデックスではなく、元の individual_df のインデックスを探す
                                            original_row_index = individual_df.index[
                                                (individual_df['timestamp'] == row['timestamp']) & 
                                                (individual_df['message'] == row['message']) 
                                            ].tolist()
                                            
                                            if original_row_index:
                                                sheet_row_index = original_row_index[0] + 2 
                                                if update_row_in_sheet(individual_sheet_name, sheet_row_index, {"read_status": new_read_status}, identifier_type="name"):
                                                    st.success(f"{student_name} の既読ステータスを '{new_read_status}' に更新しました。")
                                                    st.rerun() # 更新が成功したらrerunして表示を更新
                                                else:
                                                    st.error("既読ステータスの更新に失敗しました。")
                                            else:
                                                st.error("更新対象の連絡が見つかりませんでした。")
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
                    # support_memos_df はすでに上で読み込まれている
                    current_memo_row = support_memos_df[support_memos_df['student_name'] == selected_student_name]
                    current_memo = current_memo_row['memo_content'].iloc[0] if not current_memo_row.empty else ""

                    with st.form(key=f"support_memo_form_{selected_student_name}", clear_on_submit=False):
                        new_memo_content = st.text_area(f"{selected_student_name}の支援メモを入力してください", value=current_memo, height=250)
                        
                        submitted_memo = st.form_submit_button("メモを保存")
                        if submitted_memo:
                            if not current_memo_row.empty: 
                                sheet_row_index = current_memo_row.index[0] + 2 
                                if update_row_in_sheet(SUPPORT_MEMO_SHEET_NAME, sheet_row_index, {"memo_content": new_memo_content, "last_updated": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}, identifier_type="name"):
                                    st.success("支援メモを更新しました。")
                                    st.rerun() # 更新が成功したらrerun
                                else:
                                    st.error("支援メモの更新に失敗しました。")
                            else: 
                                new_memo_record = {
                                    "student_name": selected_student_name,
                                    "memo_content": new_memo_content,
                                    "created_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                                    "last_updated": datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                                }
                                if append_row_to_sheet(SUPPORT_MEMO_SHEET_NAME, new_memo_record, identifier_type="name"):
                                    st.success("支援メモを保存しました。")
                                    st.rerun() # 保存が成功したらrerun
                                else:
                                    st.error("支援メモの保存に失敗しました。")
                            # st.cache_data.clear() は append_row_to_sheet/update_row_in_sheet 内で行われるため削除

                    
            elif menu_selection == "カレンダー":
                st.header("カレンダー (行事予定・配布物)")
                
                # calendar_df_full はすでに上で読み込まれている
                if not calendar_df_full.empty:
                    st.subheader("今後の予定")

                    display_events = calendar_df_full[
                        calendar_df_full['target_classes'].fillna('').apply(
                            lambda x: not x or "全体" in [c.strip() for c in x.split(',')] or any(tc in [c.strip() for c in x.split(',')] for tc in st.session_state.teacher_classes)
                        )
                    ]

                    today = datetime.now().date()
                    upcoming_events = display_events[display_events['event_date'].dt.date >= today]
                    
                    if not upcoming_events.empty:
                        for index, event in upcoming_events.iterrows():
                            event_date_obj = event['event_date']
                            if pd.isna(event_date_obj): 
                                st.warning(f"カレンダーイベント '{event.get('event_name', '不明なイベント')}' に無効な日付が含まれています。")
                                continue 

                            target_classes_info = f" ({event['target_classes']})" if event['target_classes'] else ""
                            st.markdown(f"**{event_date_obj.strftime('%Y/%m/%d')}**: **{event['event_name']}**{target_classes_info} - {event['description']}")
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
                        
                        all_student_classes_df = load_sheet_data(STUDENTS_SHEET_NAME, identifier_type="name")
                        all_student_classes = []
                        if not all_student_classes_df.empty and STUDENT_CLASS_COLUMN in all_student_classes_df.columns:
                            all_student_classes = all_student_classes_df[STUDENT_CLASS_COLUMN].dropna().unique().tolist()

                        available_options = ["全体"] + list(st.session_state.teacher_classes)
                        unique_available_options = sorted(list(set(available_options)))
                        
                        default_selected_classes = []
                        if st.session_state.teacher_classes:
                            default_selected_classes = list(st.session_state.teacher_classes)
                        else:
                            default_selected_classes = ["全体"] 

                        selected_target_classes = st.multiselect(
                            "対象クラス (複数選択可、'全体'を選択すると全クラス対象)",
                            options=unique_available_options,
                            default=default_selected_classes
                        )
                        
                        event_attachment = st.file_uploader("添付ファイル (任意)", type=["pdf", "jpg", "png"])
                        
                        submitted_event = st.form_submit_button("イベントを追加")
                        if submitted_event:
                            if not event_name.strip():
                                st.error("イベント名は必須です。")
                            else:
                                attachment_url = ""
                                if event_attachment:
                                    with st.spinner("ファイルをGoogle Driveにアップロード中..."):
                                        event_attachment.seek(0) 
                                        attachment_url = upload_to_drive(event_attachment, event_attachment.name, event_attachment.type, credentials)
                                if attachment_url is None: 
                                    st.error("ファイルアップロードに失敗しました。")
                                    return 
                                    
                                new_event = {
                                    "event_date": event_date.strftime("%Y/%m/%d"),
                                    "event_name": event_name,
                                    "description": description,
                                    "attachment_url": attachment_url,
                                    "target_classes": ", ".join(selected_target_classes) 
                                }
                                if append_row_to_sheet(CALENDAR_SHEET_NAME, new_event, identifier_type="name"):
                                    st.success("イベントを追加しました！")
                                    st.rerun()
                                else:
                                    st.error("イベントの追加に失敗しました。")
                else:
                    st.info("カレンダーデータが読み込めませんでした。シート設定を確認してください。")

            elif menu_selection == "ダッシュボード":
                st.header("ダッシュボード")
                
                # NEW: ダッシュボード選択時のみ読み込む
                general_df = load_sheet_data(GENERAL_CONTACTS_SHEET_NAME, identifier_type="name") 
                general_contacts_count = len(general_df) if not general_df.empty else 0

                total_individual_contacts = 0
                total_read_individual = 0
                total_unread_individual = 0
                total_replied_individual = 0

                all_individual_contacts_df_for_dashboard = pd.DataFrame() # 月別集計用
                for student_data in associated_students_data: 
                    individual_sheet_name = student_data['individual_sheet_name']
                    individual_df = load_sheet_data(individual_sheet_name, identifier_type="name")
                    if not individual_df.empty:
                        total_individual_contacts += len(individual_df)
                        if 'read_status' in individual_df.columns:
                            total_read_individual += (individual_df['read_status'] == '既読').sum()
                            total_unread_individual += (individual_df['read_status'] == '未読').sum()
                        total_replied_individual += (individual_df['home_reply'].astype(str).str.strip() != '').sum()
                        all_individual_contacts_df_for_dashboard = pd.concat([all_individual_contacts_df_for_dashboard, individual_df])
                
                st.subheader("連絡件数概要")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("全体連絡数", general_contacts_count)
                col2.metric("個別連絡数", total_individual_contacts)
                col3.metric("個別連絡 (既読)", total_read_individual)
                col4.metric("個別連絡 (未読)", total_unread_individual)

                st.subheader("月別連絡数 (個別連絡)")
                if not all_individual_contacts_df_for_dashboard.empty:
                    all_individual_contacts_df_for_dashboard["timestamp"] = pd.to_datetime(all_individual_contacts_df_for_dashboard["timestamp"], errors='coerce') 
                    all_individual_contacts_df_for_dashboard = all_individual_contacts_df_for_dashboard.dropna(subset=['timestamp']) 
                    all_individual_contacts_df_for_dashboard["month"] = all_individual_contacts_df_for_dashboard["timestamp"].dt.to_period("M")
                    monthly_counts = all_individual_contacts_df_for_dashboard["month"].value_counts().sort_index()
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
            
            if len(associated_students_data) > 1:
                selected_student_name = st.sidebar.selectbox("お子さんを選択", student_names_only, key="parent_student_select")
            elif associated_students_data:
                selected_student_name = student_names_only[0]
                st.sidebar.info(f"連絡帳: {selected_student_name}")
            else:
                st.error("紐付けられた生徒情報がありません。")
                return # st.stop() の代わりに return

            selected_individual_sheet_name = None 
            selected_student_class = None 
            if selected_student_name:
                for student_data in associated_students_data:
                    if student_data['student_name'] == selected_student_name:
                        selected_individual_sheet_name = student_data['individual_sheet_name']
                        selected_student_class = student_data.get(STUDENT_CLASS_COLUMN) 
                        break
            if selected_individual_sheet_name is None:
                st.error(f"生徒 '{selected_student_name}' の個別連絡シート名が見つかりません。生徒情報シートを確認してください。") 
                return # st.stop() の代わりに return

            # NEW: 必要なメニュー選択時のみデータを読み込む
            general_df_parent = pd.DataFrame()
            individual_df_parent = pd.DataFrame()
            calendar_df_full_parent = pd.DataFrame()

            if menu_selection in ["自分の連絡帳", "返信作成"]:
                general_df_parent = load_sheet_data(GENERAL_CONTACTS_SHEET_NAME, identifier_type="name") 
                individual_df_parent = load_sheet_data(selected_individual_sheet_name, identifier_type="name") 

            if menu_selection == "カレンダー":
                calendar_df_full_parent = load_sheet_data(CALENDAR_SHEET_NAME, identifier_type="name")
                if calendar_df_full_parent.empty:
                    st.warning("カレンダーデータが読み込めませんでした。シート名または権限を確認してください。")
                    calendar_df_full_parent = pd.DataFrame(columns=['event_date', 'event_name', 'description', 'attachment_url', 'target_classes'])
                
                if 'target_classes' not in calendar_df_full_parent.columns:
                    calendar_df_full_parent['target_classes'] = '' 
                
                if 'event_date' in calendar_df_full_parent.columns:
                    calendar_df_full_parent['event_date'] = pd.to_datetime(calendar_df_full_parent['event_date'], format='%Y/%m/%d', errors='coerce')
                    calendar_df_full_parent = calendar_df_full_parent.dropna(subset=['event_date']) 
                else:
                    calendar_df_full_parent = pd.DataFrame(columns=['event_date', 'event_name', 'description', 'attachment_url', 'target_classes'])

                if not calendar_df_full_parent.empty and 'event_date' in calendar_df_full_parent.columns:
                    calendar_df_full_parent = calendar_df_full_parent.sort_values(by='event_date')


            if menu_selection == "自分の連絡帳":
                st.header(f"{selected_student_name} 連絡帳")
                
                st.subheader("📢 全体連絡")
                if not general_df_parent.empty:
                    general_df_parent["timestamp"] = pd.to_datetime(general_df_parent["timestamp"], errors='coerce') 
                    general_df_parent = general_df_parent.dropna(subset=['timestamp']) 
                    general_df_parent = general_df_parent.sort_values(by="timestamp", ascending=False).reset_index(drop=True)
                    
                    for index, row in general_df_parent.iterrows():
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

                st.subheader(f"🧑‍🏫 {selected_student_name} への個別連絡")
                if not individual_df_parent.empty:
                    individual_df_parent["timestamp"] = pd.to_datetime(individual_df_parent["timestamp"], errors='coerce') 
                    individual_df_parent = individual_df_parent.dropna(subset=['timestamp']) 
                    if 'read_status' not in individual_df_parent.columns:
                        individual_df_parent['read_status'] = '未読'
                    individual_df_parent = individual_df_parent.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                    for index, row in individual_df_parent.iterrows():
                        expander_key_parent = f"expander_parent_{selected_student_name}_{index}"
                        with st.expander(f"📅 {row['date']} - {row['sender']} ({row['read_status']})", expanded=False, key=expander_key_parent):
                            st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                            st.info(f"**学校からの連絡:** {row['message']}")
                            if row['home_reply']:
                                st.success(f"**あなたの返信:** {row['home_reply']}")
                            if row['items_notice']:
                                st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                            # 保護者には備考を表示しない
                            # if row['remarks']:
                            #     st.caption(f"**備考:** {row['remarks']}")
                            if row['image_url']:
                                if row['image_url'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    st.image(row['image_url'], caption="添付画像", width=300)
                                elif row['image_url'].lower().endswith(('.pdf')):
                                    st.markdown(f"**添付PDF:** [こちらをクリックして閲覧]({row['image_url']})")
                                else:
                                    st.markdown(f"**添付ファイル:** [ファイルリンク]({row['image_url']})")
                            
                            # NEW: 既読ボタンの処理を修正
                            unique_read_button_key = f"read_button_parent_{selected_student_name}_{index}"
                            if row['read_status'] == '未読':
                                if unique_read_button_key not in st.session_state.read_button_clicked:
                                    st.session_state.read_button_clicked[unique_read_button_key] = False
                                
                                if not st.session_state.read_button_clicked[unique_read_button_key]:
                                    st.info("この連絡はまだ既読になっていません。")
                                    if st.button("既読にする", key=unique_read_button_key):
                                        original_row_index = individual_df_parent.index[
                                            (individual_df_parent['timestamp'] == row['timestamp']) &
                                            (individual_df_parent['message'] == row['message']) 
                                        ].tolist()
                                        
                                        if original_row_index:
                                            sheet_row_index = original_row_index[0] + 2 
                                            if update_row_in_sheet(selected_individual_sheet_name, sheet_row_index, {"read_status": "既読"}, identifier_type="name"): 
                                                st.session_state.read_button_clicked[unique_read_button_key] = True # 状態を更新
                                                st.success("連絡を既読にしました。")
                                                st.rerun() # 既読にしたらrerunして表示を更新
                                            else:
                                                st.error("既読ステータスの更新に失敗しました。")
                                        else:
                                            st.error("更新対象の連絡が見つかりませんでした。")
                            else:
                                st.success("この連絡は既読です。")
                        st.markdown("---")
                else:
                    st.info(f"{selected_student_name} への個別連絡はまだありません。")

            elif menu_selection == "返信作成":
                st.header(f"{selected_student_name} からの返信作成")
                st.info("返信したい個別連絡を選択してください。")

                # individual_df_parent はすでに上で読み込まれている
                if not individual_df_parent.empty:
                    individual_df_parent["timestamp"] = pd.to_datetime(individual_df_parent["timestamp"], errors='coerce') 
                    individual_df_parent = individual_df_parent.dropna(subset=['timestamp']) 
                    
                    reply_needed_df = individual_df_parent[
                        (individual_df_parent["home_reply"].astype(str).str.strip() == "")
                    ]

                    if not reply_needed_df.empty:
                        latest_unreplied = reply_needed_df.sort_values(by="timestamp", ascending=False).iloc[0]
                        
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
                                            uploaded_file_reply.seek(0) 
                                            image_url_reply = upload_to_drive(uploaded_file_reply, uploaded_file_reply.name, uploaded_file_reply.type, credentials)
                                    if image_url_reply is None: 
                                        st.error("画像アップロードに失敗しました。再度お試しください。")
                                        return 
                                        
                                    original_row_index = individual_df_parent.index[
                                        (individual_df_parent['timestamp'] == latest_unreplied['timestamp']) &
                                        (individual_df_parent['message'] == latest_unreplied['message'])
                                    ].tolist()
                                    
                                    if original_row_index:
                                        sheet_row_index = original_row_index[0] + 2 
                                        data_to_update = {"home_reply": home_reply}
                                        if image_url_reply:
                                            data_to_update["image_url"] = image_url_reply
                                        
                                        if update_row_in_sheet(selected_individual_sheet_name, sheet_row_index, data_to_update, identifier_type="name"):
                                            st.success("返信を送信しました！")
                                            st.balloons()
                                            st.rerun() # 返信が成功したらrerun
                                        else:
                                            st.error("返信の保存に失敗しました。")
                                    else:
                                        st.error("返信対象の連絡が見つかりませんでした。")
                    else:
                        st.info("返信する未返信の個別連絡はありません。")
                else:
                    st.info("個別連絡データがありません。")
            
            elif menu_selection == "カレンダー":
                st.header("カレンダー (行事予定・配布物)")
                
                # calendar_df_full_parent はすでに上で読み込まれている
                if not calendar_df_full_parent.empty:
                    st.subheader("今後の予定")
                    today = datetime.now().date()
                    
                    parent_display_events = calendar_df_full_parent[
                        calendar_df_full_parent['target_classes'].fillna('').apply(
                            lambda x: not x or "全体" in [c.strip() for c in x.split(',')] or (selected_student_class and selected_student_class in [c.strip() for c in x.split(',')])
                        )
                    ]

                    upcoming_events = parent_display_events[parent_display_events['event_date'].dt.date >= today]
                    
                    if not upcoming_events.empty:
                        for index, event in upcoming_events.iterrows():
                            event_date_obj = event['event_date']
                            if pd.isna(event_date_obj): 
                                st.warning(f"カレンダーイベント '{event.get('event_name', '不明なイベント')}' に無効な日付が含まれています。")
                                continue 

                            target_classes_info = f" ({event['target_classes']})" if event['target_classes'] else ""
                            st.markdown(f"**{event_date_obj.strftime('%Y/%m/%d')}**: **{event['event_name']}**{target_classes_info} - {event['description']}")
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
        
        st.markdown("---")
        st.markdown(f"当アプリをご利用になる前に、[プライバシーポリシー]({PRIVACY_POLICY_URL})と[利用規約]({TERMS_OF_SERVICE_URL})をご確認ください。", unsafe_allow_html=True)

        st.markdown("新しい教育ツールのイメージです。")
        # ログイン前のイメージ
        
if __name__ == "__main__":
    main()