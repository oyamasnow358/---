import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import psycopg2
from psycopg2 import sql
import os
import bcrypt # パスワードハッシュ化のために追加

# --- 定数設定 ---
PRIVACY_POLICY_URL = "https://docs.google.com/document/d/1uJX0GOorVXEutA7IKJOyBG6tZrLDesE7y_zAZGbSsKg/edit?tab=t.0"
TERMS_OF_SERVICE_URL = "https://docs.google.com/document/d/171oLSgxk55KCZhdTSJf0R3ibTWoIQPPrlQvz8EgAA0s/edit?tab=t.0"

# 環境変数から設定を読み込む
DATABASE_URL = os.environ.get("DATABASE_URL")
TEACHER_CLASS_COLUMN = os.environ.get("TEACHER_CLASS_COLUMN", "class_name")
STUDENT_CLASS_COLUMN = os.environ.get("STUDENT_CLASS_COLUMN", "class_name")

# テーブル名（正規化されたモデルに合わせた名前）
TABLE_GENERAL_CONTACTS = "general_contacts"
TABLE_STUDENTS = "students"
TABLE_TEACHERS = "teachers"
TABLE_SUPPORT_MEMOS = "support_memos"
TABLE_CALENDAR_EVENTS = "calendar_events"
TABLE_INDIVIDUAL_CONTACTS = "individual_contacts"

# --- Streamlitセッション状態の初期化 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_info' not in st.session_state:
    st.session_state.user_info = None # {'id': '...', 'email': '...', 'name': '...'}
if 'user_role' not in st.session_state:
    st.session_state.user_role = None  # 'teacher' or 'parent'
if 'associated_students_data' not in st.session_state:
    st.session_state.associated_students_data = [] # {student_id: "", student_name: "", class_name: ""}
if 'teacher_classes' not in st.session_state:
    st.session_state.teacher_classes = []
if 'data_loaded_on_login' not in st.session_state:
    st.session_state.data_loaded_on_login = False
if 'general_contacts_df' not in st.session_state:
    st.session_state.general_contacts_df = pd.DataFrame()
if 'students_df_global' not in st.session_state:
    st.session_state.students_df_global = pd.DataFrame()
if 'teachers_df_global' not in st.session_state:
    st.session_state.teachers_df_global = pd.DataFrame()
if 'calendar_df_full' not in st.session_state:
    st.session_state.calendar_df_full = pd.DataFrame()

# --- データベースヘルパー関数 ---
def get_db_connection():
    """データベース接続を確立する"""
    if DATABASE_URL is None:
        st.error("DATABASE_URL 環境変数が設定されていません。")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        st.error(f"データベース接続に失敗しました: {e}", icon="🚨")
        st.exception(e)
        return None

def hash_password(password):
    """パスワードをbcryptでハッシュ化する"""
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')

def check_password(password, hashed_password):
    """パスワードとハッシュ化されたパスワードを比較する"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def init_db():
    """データベーステーブルを初期化（存在しない場合のみ作成）"""
    conn = get_db_connection()
    if conn is None:
        return

    cur = conn.cursor()
    try:
        # students テーブル
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_STUDENTS} (
                id SERIAL PRIMARY KEY,
                student_name VARCHAR(255) NOT NULL,
                parent_email VARCHAR(255) UNIQUE NOT NULL,
                parent_password_hash VARCHAR(255) NOT NULL,
                {STUDENT_CLASS_COLUMN} VARCHAR(255)
            );
        """)
        # teachers テーブル
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_TEACHERS} (
                id SERIAL PRIMARY KEY,
                teacher_name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                {TEACHER_CLASS_COLUMN} TEXT -- カンマ区切りで複数クラスを保持
            );
        """)
        # general_contacts テーブル (画像URLは削除)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_GENERAL_CONTACTS} (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                contact_date DATE,
                sender VARCHAR(255),
                message TEXT,
                items_notice TEXT
            );
        """)
        # support_memos テーブル (student_idで紐付け)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_SUPPORT_MEMOS} (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES {TABLE_STUDENTS}(id) ON DELETE CASCADE,
                memo_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # calendar_events テーブル (画像URLは削除)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_CALENDAR_EVENTS} (
                id SERIAL PRIMARY KEY,
                event_date DATE,
                event_name VARCHAR(255),
                description TEXT,
                target_classes TEXT -- カンマ区切りで複数クラスを保持
            );
        """)
        # individual_contacts テーブル (student_idで紐付け、画像URLは削除)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_INDIVIDUAL_CONTACTS} (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES {TABLE_STUDENTS}(id) ON DELETE CASCADE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                contact_date DATE,
                sender VARCHAR(255),
                message TEXT,
                home_reply TEXT,
                items_notice TEXT,
                remarks TEXT
            );
        """)
        conn.commit()
    except Exception as e:
        st.error(f"データベーステーブルの初期化に失敗しました: {e}", icon="🚨")
        st.exception(e)
    finally:
        cur.close()
        conn.close()

# アプリケーション起動時にDB初期化
init_db()

@st.cache_data(ttl=300) # キャッシュ期間を5分に設定
def db_read(table_name, student_id=None):
    """データベースからデータを読み込む"""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    try:
        if table_name == TABLE_INDIVIDUAL_CONTACTS and student_id is not None:
            query = sql.SQL(f"SELECT * FROM {TABLE_INDIVIDUAL_CONTACTS} WHERE student_id = %s ORDER BY timestamp DESC")
            df = pd.read_sql(query.as_string(conn), conn, params=(student_id,))
        elif table_name == TABLE_SUPPORT_MEMOS and student_id is not None:
            query = sql.SQL(f"SELECT * FROM {TABLE_SUPPORT_MEMOS} WHERE student_id = %s ORDER BY last_updated DESC")
            df = pd.read_sql(query.as_string(conn), conn, params=(student_id,))
        else:
            # timestamp 列がないテーブルもあるので、SELECT * で取得
            query = sql.SQL(f"SELECT * FROM {sql.Identifier(table_name)}")
            df = pd.read_sql(query.as_string(conn), conn)
            # 各テーブルのデフォルトソートをここで指定
            if table_name in [TABLE_GENERAL_CONTACTS, TABLE_CALENDAR_EVENTS]:
                if 'timestamp' in df.columns:
                    df = df.sort_values(by="timestamp", ascending=False)
                elif 'event_date' in df.columns:
                    df = df.sort_values(by="event_date", ascending=False)
        return df
    except Exception as e:
        st.error(f"テーブル '{table_name}' の読み込み中にエラーが発生しました: {e}", icon="🚨")
        st.exception(e)
        return pd.DataFrame()
    finally:
        conn.close()

def db_insert(table_name, data):
    """データベースにデータを追加する"""
    conn = get_db_connection()
    if conn is None:
        return False
    cur = conn.cursor()
    try:
        columns = sql.SQL(', ').join(sql.Identifier(col) for col in data.keys())
        placeholders = sql.SQL(', ').join(sql.Placeholder() for _ in data.keys())
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format( # idを返すように変更
            sql.Identifier(table_name), columns, placeholders
        )
        cur.execute(query, list(data.values()))
        new_id = cur.fetchone()[0] # 挿入されたIDを取得
        conn.commit()
        st.cache_data.clear() # キャッシュをクリア
        return new_id # 挿入されたIDを返す
    except Exception as e:
        st.error(f"テーブル '{table_name}' へのデータ追加中にエラーが発生しました: {e}", icon="🚨")
        st.exception(e)
        return False
    finally:
        cur.close()
        conn.close()

def db_update(table_name, record_id, data):
    """データベースの指定レコードを更新する"""
    conn = get_db_connection()
    if conn is None:
        return False
    cur = conn.cursor()
    try:
        set_clause = sql.SQL(', ').join(
            sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder())
            for col in data.keys()
        )
        query = sql.SQL("UPDATE {} SET {} WHERE id = {}").format(
            sql.Identifier(table_name), set_clause, sql.Placeholder()
        )
        cur.execute(query, list(data.values()) + [record_id])
        conn.commit()
        st.cache_data.clear() # キャッシュをクリア
        return True
    except Exception as e:
        st.error(f"テーブル '{table_name}' のレコード更新中にエラーが発生しました: {e}", icon="🚨")
        st.exception(e)
        return False
    finally:
        cur.close()
        conn.close()

# --- 認証関数 ---
def authenticate_user(email, password):
    """ユーザーを認証し、役割と情報を返す"""
    conn = get_db_connection()
    if conn is None:
        return None, None

    cur = conn.cursor()
    try:
        # 教員として認証を試みる
        cur.execute(f"SELECT id, teacher_name, email, password_hash, {TEACHER_CLASS_COLUMN} FROM {TABLE_TEACHERS} WHERE email = %s", (email,))
        teacher_row = cur.fetchone()
        if teacher_row:
            teacher_id, teacher_name, teacher_email, hashed_password, teacher_classes_raw = teacher_row
            if check_password(password, hashed_password):
                st.session_state.logged_in = True
                st.session_state.user_info = {'id': teacher_id, 'email': teacher_email, 'name': teacher_name}
                st.session_state.user_role = 'teacher'
                st.session_state.teacher_classes = [c.strip() for c in teacher_classes_raw.split(',') if c.strip()] if teacher_classes_raw else []

                # すべての生徒情報をロード
                st.session_state.students_df_global = db_read(TABLE_STUDENTS)
                if st.session_state.students_df_global.empty:
                    st.error("生徒データが読み込めませんでした。生徒テーブルを確認してください。", icon="🚨")
                    st.session_state.logged_in = False
                    return None, None

                if not st.session_state.teacher_classes:
                    all_classes = st.session_state.students_df_global[STUDENT_CLASS_COLUMN].dropna().unique().tolist()
                    st.session_state.teacher_classes = all_classes
                    st.sidebar.warning("担当クラスが設定されていないため、すべてのクラスを対象とします。")
                else:
                    st.sidebar.info(f"担当クラス: {', '.join(st.session_state.teacher_classes)}")

                filtered_students_df = st.session_state.students_df_global[
                    st.session_state.students_df_global[STUDENT_CLASS_COLUMN].isin(st.session_state.teacher_classes)
                ]
                st.session_state.associated_students_data = filtered_students_df[
                    ['id', 'student_name', STUDENT_CLASS_COLUMN]
                ].rename(columns={'id': 'student_id'}).to_dict(orient='records')

                st.success("教員としてログインしました！")
                return st.session_state.user_info, 'teacher'

        # 保護者として認証を試みる
        cur.execute(f"SELECT id, student_name, parent_email, parent_password_hash, {STUDENT_CLASS_COLUMN} FROM {TABLE_STUDENTS} WHERE parent_email = %s", (email,))
        student_row = cur.fetchone()
        if student_row:
            student_id, student_name, parent_email, hashed_password, student_class = student_row
            if check_password(password, hashed_password):
                st.session_state.logged_in = True
                st.session_state.user_info = {'id': student_id, 'email': parent_email, 'name': f"{student_name}の保護者"}
                st.session_state.user_role = 'parent'
                st.session_state.associated_students_data = [{
                    'student_id': student_id,
                    'student_name': student_name,
                    STUDENT_CLASS_COLUMN: student_class
                }]
                st.session_state.students_df_global = db_read(TABLE_STUDENTS)

                st.success("保護者としてログインしました！")
                return st.session_state.user_info, 'parent'

        st.error("メールアドレスまたはパスワードが正しくありません。", icon="❌")
        return None, None
    except Exception as e:
        st.error(f"認証中にエラーが発生しました: {e}", icon="🚨")
        st.exception(e)
        return None, None
    finally:
        cur.close()
        conn.close()

# --- ユーザー登録関数 (初期データ投入用、管理者のみがアクセスすべき) ---
def register_user_admin_only(role, name, email, password, class_info=None):
    if role == 'teacher':
        table = TABLE_TEACHERS
        data = {
            'teacher_name': name,
            'email': email,
            'password_hash': hash_password(password),
            TEACHER_CLASS_COLUMN: class_info if class_info else ""
        }
    elif role == 'parent':
        table = TABLE_STUDENTS
        data = {
            'student_name': name.split('の保護者')[0].strip(), # "生徒名 の保護者" から生徒名を取得
            'parent_email': email,
            'parent_password_hash': hash_password(password),
            STUDENT_CLASS_COLUMN: class_info if class_info else ""
        }
    else:
        st.error("無効なロールです。", icon="❌")
        return False

    try:
        if db_insert(table, data):
            st.success(f"{name} ({role}) が登録されました！", icon="✅")
            return True
        else:
            st.error(f"{role} の登録に失敗しました。", icon="❌")
            return False
    except Exception as e:
        st.error(f"ユーザー登録エラー: {e}", icon="🚨")
        return False

# --- ログイン画面を表示する関数 ---
def show_login_form():
    st.sidebar.header("ログイン")
    email = st.sidebar.text_input("メールアドレス", key="login_email")
    password = st.sidebar.text_input("パスワード", type="password", key="login_password")

    if st.sidebar.button("ログイン", key="login_button"):
        if email and password:
            user_info, user_role = authenticate_user(email, password)
            if user_info:
                if not st.session_state.data_loaded_on_login:
                    st.session_state.general_contacts_df = db_read(TABLE_GENERAL_CONTACTS)
                    st.session_state.calendar_df_full = db_read(TABLE_CALENDAR_EVENTS)

                    # カレンダーデータフレームの処理
                    if st.session_state.calendar_df_full.empty:
                        st.warning("カレンダーデータが読み込めませんでした。テーブルを確認してください。", icon="⚠️")
                        st.session_state.calendar_df_full = pd.DataFrame(columns=['id', 'event_date', 'event_name', 'description', 'target_classes'])

                    if 'event_date' in st.session_state.calendar_df_full.columns:
                        st.session_state.calendar_df_full['event_date'] = pd.to_datetime(st.session_state.calendar_df_full['event_date'], errors='coerce')
                        st.session_state.calendar_df_full = st.session_state.calendar_df_full.dropna(subset=['event_date'])
                    else:
                        st.session_state.calendar_df_full = pd.DataFrame(columns=['id', 'event_date', 'event_name', 'description', 'target_classes'])

                    if not st.session_state.calendar_df_full.empty and 'event_date' in st.session_state.calendar_df_full.columns:
                        st.session_state.calendar_df_full = st.session_state.calendar_df_full.sort_values(by='event_date')

                    st.session_state.data_loaded_on_login = True
                st.rerun()
            # エラーメッセージはauthenticate_user内で表示される
        else:
            st.sidebar.warning("メールアドレスとパスワードを入力してください。", icon="⚠️")

    st.sidebar.markdown(f'[プライバシーポリシー]({PRIVACY_POLICY_URL})', unsafe_allow_html=True)
    st.sidebar.markdown(f'[利用規約]({TERMS_OF_SERVICE_URL})', unsafe_allow_html=True)

# --- Streamlitアプリ本体 ---
def main():
    st.set_page_config(layout="wide", page_title="デジタル連絡帳")
    st.title("🌟 特別支援学校向け デジタル連絡帳")
    st.markdown("---")

    # 管理者用ユーザー登録フォーム (開発・初期設定用。本番環境ではアクセスを制限すべき)
    with st.expander("管理者用: ユーザー登録 (開発・初期設定用)", expanded=False):
        st.warning("このセクションは管理者専用です。本番環境では無効にするか、厳重なアクセス制限を設けてください。", icon="⚠️")
        reg_role = st.radio("登録ロール", ['teacher', 'parent'], key="reg_role")
        reg_name = st.text_input("名前 (保護者の場合は「生徒名 の保護者」)", key="reg_name")
        reg_email = st.text_input("メールアドレス", key="reg_email")
        reg_password = st.text_input("パスワード", type="password", key="reg_password")
        reg_class_info = st.text_input("クラス情報 (教員: カンマ区切り, 保護者: 単一クラス)", key="reg_class_info")

        if st.button("ユーザー登録", key="register_user_button"):
            if reg_name and reg_email and reg_password:
                register_user_admin_only(reg_role, reg_name, reg_email, reg_password, reg_class_info)
            else:
                st.error("すべてのフィールドを入力してください。", icon="❌")

    if not st.session_state.logged_in:
        show_login_form()
        st.markdown("デジタル連絡帳へようこそ！")
        st.markdown("このアプリは、特別支援学校の先生と保護者の皆様が、安全かつ効率的に連絡を取り合うためのツールです。")
        st.markdown("---")
        st.write("主な機能:")
        st.markdown("- 学校と家庭間の連絡をオンラインで完結")
        st.markdown("- 過去のやり取りを自動保存し、振り返りや支援記録にも活用可能")
        st.markdown("---")
        st.markdown(f"当アプリをご利用になる前に、[プライバシーポリシー]({PRIVACY_POLICY_URL})と[利用規約]({TERMS_OF_SERVICE_URL})をご確認ください。", unsafe_allow_html=True)
        st.markdown("新しい教育ツールのイメージです。")
        st.stop()

    user_name = st.session_state.user_info.get('name', st.session_state.user_info['email'])
    user_role = st.session_state.user_role

    associated_students_data = st.session_state.associated_students_data
    student_names_only = [s['student_name'] for s in associated_students_data]

    st.sidebar.success(f"ようこそ、{user_name}さん！ ({'教員' if user_role == 'teacher' else '保護者'})", icon="👋")

    if st.sidebar.button("ログアウト", key="logout_button"):
        st.session_state.logged_in = False
        st.session_state.user_info = None
        st.session_state.user_role = None
        st.session_state.associated_students_data = []
        st.session_state.teacher_classes = []
        st.session_state.data_loaded_on_login = False
        st.session_state.general_contacts_df = pd.DataFrame()
        st.session_state.calendar_df_full = pd.DataFrame()
        st.session_state.students_df_global = pd.DataFrame()
        st.session_state.teachers_df_global = pd.DataFrame()
        st.rerun()

    st.sidebar.header("ナビゲーション")

    # 全体連絡とカレンダーはログイン時にSession Stateにロード済み
    general_df = st.session_state.general_contacts_df
    calendar_df_full = st.session_state.calendar_df_full

    # --- 教員画面 ---
    if user_role == 'teacher':
        st.sidebar.subheader("教員メニュー")
        menu_selection = st.sidebar.radio(
            "機能を選択", ["個別連絡作成", "全体連絡作成", "連絡帳一覧", "生徒別支援メモ", "カレンダー", "ダッシュボード"]
        )

        student_options = ["全体"] + student_names_only
        selected_student_name = st.sidebar.selectbox("対象生徒を選択", student_options, key="teacher_student_select")

        selected_student_id = None
        selected_student_class = None
        if selected_student_name != "全体":
            for student_data in associated_students_data:
                if student_data['student_name'] == selected_student_name:
                    selected_student_id = student_data['student_id']
                    selected_student_class = student_data.get(STUDENT_CLASS_COLUMN)
                    break
            if selected_student_id is None:
                st.error(f"生徒 '{selected_student_name}' のIDが見つかりません。生徒情報テーブルを確認してください。", icon="❌")
                st.stop() # IDが見つからない場合は処理を中断

        if menu_selection == "個別連絡作成":
            if selected_student_name == "全体":
                st.warning("個別連絡作成では「全体」を選択できません。特定の生徒を選択してください。", icon="⚠️")
            elif selected_student_id:
                st.header(f"個別連絡作成: {selected_student_name} 宛")
                with st.form("individual_contact_form", clear_on_submit=True):
                    contact_date = st.date_input("連絡対象日付", datetime.now().date())
                    school_message = st.text_area("学校からの連絡内容", height=150, placeholder="今日の様子や、伝えたいことを入力してください。")
                    items_notice = st.text_input("持ち物・特記事項", placeholder="明日の持ち物など、特記事項があれば入力してください。")
                    remarks = st.text_area("備考（教員用、必要であれば）", placeholder="保護者には表示されません。", help="内部メモとして利用できます。")
                    submitted = st.form_submit_button("個別連絡を送信")

                    if submitted:
                        if not school_message.strip():
                            st.error("連絡内容は必須です。", icon="❌")
                        else:
                            new_record = {
                                "student_id": selected_student_id,
                                "timestamp": datetime.now(),
                                "contact_date": contact_date,
                                "sender": user_name,
                                "message": school_message,
                                "home_reply": "",
                                "items_notice": items_notice,
                                "remarks": remarks,
                            }
                            if db_insert(TABLE_INDIVIDUAL_CONTACTS, new_record):
                                st.success(f"個別連絡を {selected_student_name} に送信しました！", icon="✅")
                                st.balloons()
                            else:
                                st.error("個別連絡の送信に失敗しました。", icon="❌")
            else:
                st.info("生徒が選択されていないか、生徒のIDが見つかりません。", icon="ℹ️")

        elif menu_selection == "全体連絡作成":
            st.header("全体連絡作成")
            with st.form("general_contact_form", clear_on_submit=True):
                contact_date = st.date_input("連絡対象日付", datetime.now().date())
                school_message = st.text_area("全体への連絡内容", height=200, placeholder="全体へのお知らせや共有事項を入力してください。")
                items_notice = st.text_input("持ち物・特記事項", placeholder="全体への持ち物など、特記事項があれば入力してください。")
                submitted = st.form_submit_button("全体連絡を送信")

                if submitted:
                    if not school_message.strip():
                        st.error("連絡内容は必須です。", icon="❌")
                    else:
                        new_record = {
                            "timestamp": datetime.now(),
                            "contact_date": contact_date,
                            "sender": user_name,
                            "message": school_message,
                            "items_notice": items_notice,
                        }
                        if db_insert(TABLE_GENERAL_CONTACTS, new_record):
                            st.success("全体連絡を送信しました！", icon="✅")
                            st.balloons()
                            st.session_state.general_contacts_df = db_read(TABLE_GENERAL_CONTACTS) # セッション状態を更新
                        else:
                            st.error("全体連絡の送信に失敗しました。", icon="❌")

        elif menu_selection == "連絡帳一覧":
            st.header("連絡帳一覧")
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                contact_type_filter = st.selectbox("連絡種別で絞り込み", ["すべて", "全体連絡", "個別連絡"], key="contact_type_filter_teacher")
            with filter_col2:
                search_query = st.text_input("キーワード検索", placeholder="連絡内容、備考などで検索...", key="search_query_teacher")

            st.subheader("📢 全体連絡")
            if not general_df.empty:
                general_df_display = general_df.copy()
                general_df_display["timestamp"] = pd.to_datetime(general_df_display["timestamp"])
                general_df_display = general_df_display.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                if search_query:
                    general_df_display = general_df_display[
                        general_df_display.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                    ]

                if contact_type_filter in ["すべて", "全体連絡"]:
                    if not general_df_display.empty:
                        for index, row in general_df_display.iterrows():
                            with st.expander(f"📅 {row['contact_date'].strftime('%Y/%m/%d')} - {row['sender']} (全体連絡)", expanded=False):
                                st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                                st.info(f"**連絡内容:** {row['message']}")
                                if row['items_notice']:
                                    st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                                st.markdown("---")
                    else:
                        st.info("全体連絡はまだありません。", icon="ℹ️")
            else:
                st.info("全体連絡データが読み込めませんでした。", icon="ℹ️")

            st.subheader("🧑‍🏫 個別連絡")
            if contact_type_filter in ["すべて", "個別連絡"]:
                for student_data in associated_students_data:
                    student_name = student_data['student_name']
                    student_id = student_data['student_id']
                    st.markdown(f"##### {student_name} の連絡")

                    # 個別連絡はSession Stateに保持せず、都度DBから読み込む
                    individual_df = db_read(TABLE_INDIVIDUAL_CONTACTS, student_id=student_id)
                    if not individual_df.empty:
                        individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"])
                        individual_df = individual_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)
                        display_individual_df = individual_df.copy()

                        if search_query:
                            display_individual_df = display_individual_df[
                                display_individual_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                            ]

                        if not display_individual_df.empty:
                            for index, row in display_individual_df.iterrows():
                                with st.expander(f"📅 {row['contact_date'].strftime('%Y/%m/%d')} - {row['sender']}", expanded=False):
                                    st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                                    st.info(f"**学校からの連絡:** {row['message']}")
                                    if row['home_reply']:
                                        st.success(f"**家庭からの返信:** {row['home_reply']}")
                                    if row['items_notice']:
                                        st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                                    if row['remarks']:
                                        st.caption(f"**備考:** {row['remarks']}")
                                    st.markdown("---")
                        else:
                            st.info(f"{student_name} の個別連絡はまだありません。", icon="ℹ️")
                    else:
                        st.info(f"{student_name} の個別連絡データが読み込めませんでした。", icon="ℹ️")
                    st.markdown("---")

        elif menu_selection == "生徒別支援メモ":
            st.header(f"{selected_student_name} 支援メモ (教員専用)")
            st.info("このメモは保護者には公開されません。", icon="🔒")
            if selected_student_name == "全体":
                st.warning("「全体」の支援メモは作成できません。特定の生徒を選択してください。", icon="⚠️")
            elif selected_student_id:
                # 支援メモはSession Stateに保持せず、都度DBから読み込む
                support_memos_df = db_read(TABLE_SUPPORT_MEMOS, student_id=selected_student_id)
                current_memo_row = support_memos_df[support_memos_df['student_id'] == selected_student_id]
                current_memo = current_memo_row['memo_content'].iloc[0] if not current_memo_row.empty else ""

                with st.form(key=f"support_memo_form_{selected_student_id}", clear_on_submit=False):
                    new_memo_content = st.text_area(f"{selected_student_name}の支援メモを入力してください", value=current_memo, height=250, key=f"memo_content_{selected_student_id}")
                    submitted_memo = st.form_submit_button("メモを保存", key=f"submit_memo_{selected_student_id}")
                    if submitted_memo:
                        if not current_memo_row.empty:
                            # 既存のメモがある場合
                            record_id = current_memo_row['id'].iloc[0]
                            data_to_update = {
                                "memo_content": new_memo_content,
                                "last_updated": datetime.now()
                            }
                            if db_update(TABLE_SUPPORT_MEMOS, record_id, data_to_update):
                                st.success("支援メモを更新しました。", icon="✅")
                            else:
                                st.error("支援メモの更新に失敗しました。", icon="❌")
                        else:
                            # 新しいメモの場合
                            new_memo_record = {
                                "student_id": selected_student_id,
                                "memo_content": new_memo_content,
                                "created_at": datetime.now(),
                                "last_updated": datetime.now()
                            }
                            if db_insert(TABLE_SUPPORT_MEMOS, new_memo_record):
                                st.success("支援メモを保存しました。", icon="✅")
                            else:
                                st.error("支援メモの保存に失敗しました。", icon="❌")
                        # 成功した場合、再度データを読み込んで表示を更新
                        st.rerun()
            else:
                st.info("生徒が選択されていないか、生徒のIDが見つかりません。", icon="ℹ️")

        elif menu_selection == "カレンダー":
            st.header("カレンダー (行事予定・配布物)")
            if not calendar_df_full.empty:
                st.subheader("今後の予定")
                # 教員が担当クラスを持つ場合、そのクラスと「全体」のイベントをフィルタリング
                display_events = calendar_df_full[
                    calendar_df_full['target_classes'].fillna('').apply(
                        lambda x: not x or "全体" in [c.strip() for c in x.split(',')] or any(tc in [c.strip() for c in x.split(',')] for tc in st.session_state.teacher_classes)
                    )
                ]
                today = datetime.now().date()
                upcoming_events = display_events[display_events['event_date'].dt.date >= today]

                if not upcoming_events.empty:
                    upcoming_events = upcoming_events.sort_values(by='event_date') # 日付でソート
                    for index, event in upcoming_events.iterrows():
                        event_date_obj = event['event_date']
                        if pd.isna(event_date_obj):
                            st.warning(f"カレンダーイベント '{event.get('event_name', '不明なイベント')}' に無効な日付が含まれています。", icon="⚠️")
                            continue
                        target_classes_info = f" ({event['target_classes']})" if event['target_classes'] else ""
                        st.markdown(f"**{event_date_obj.strftime('%Y/%m/%d')}**: **{event['event_name']}**{target_classes_info} - {event['description']}")
                        st.markdown("---")
                else:
                    st.info("今後のイベントはありません。", icon="ℹ️")

                st.subheader("新規イベント追加")
                with st.form("add_event_form", clear_on_submit=True):
                    event_date = st.date_input("日付", datetime.now().date())
                    event_name = st.text_input("イベント名")
                    description = st.text_area("説明")
                    all_student_classes_df = st.session_state.students_df_global
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
                    submitted_event = st.form_submit_button("イベントを追加")

                    if submitted_event:
                        if not event_name.strip():
                            st.error("イベント名は必須です。", icon="❌")
                        else:
                            new_event = {
                                "event_date": event_date,
                                "event_name": event_name,
                                "description": description,
                                "target_classes": ", ".join(selected_target_classes)
                            }
                            if db_insert(TABLE_CALENDAR_EVENTS, new_event):
                                st.success("イベントを追加しました！", icon="✅")
                                st.session_state.calendar_df_full = db_read(TABLE_CALENDAR_EVENTS) # セッション状態を更新
                                if 'event_date' in st.session_state.calendar_df_full.columns:
                                    st.session_state.calendar_df_full['event_date'] = pd.to_datetime(st.session_state.calendar_df_full['event_date'], errors='coerce')
                                    st.session_state.calendar_df_full = st.session_state.calendar_df_full.dropna(subset=['event_date'])
                                if not st.session_state.calendar_df_full.empty and 'event_date' in st.session_state.calendar_df_full.columns:
                                    st.session_state.calendar_df_full = st.session_state.calendar_df_full.sort_values(by='event_date')
                                st.rerun()
                            else:
                                st.error("イベントの追加に失敗しました。", icon="❌")
            else:
                st.info("カレンダーデータが読み込めませんでした。テーブル設定を確認してください。", icon="ℹ️")

        elif menu_selection == "ダッシュボード":
            st.header("ダッシュボード")
            general_contacts_count = len(general_df) if not general_df.empty else 0
            total_individual_contacts = 0
            total_replied_individual = 0

            for student_data in associated_students_data:
                student_id = student_data['student_id']
                individual_df = db_read(TABLE_INDIVIDUAL_CONTACTS, student_id=student_id)
                if not individual_df.empty:
                    total_individual_contacts += len(individual_df)
                    total_replied_individual += (individual_df['home_reply'].astype(str).str.strip() != '').sum()

            st.subheader("連絡件数概要")
            col1, col2, col3 = st.columns(3)
            col1.metric("全体連絡数", general_contacts_count, icon="📣")
            col2.metric("個別連絡数", total_individual_contacts, icon="🧑‍🏫")
            col3.metric("個別連絡 (返信済)", total_replied_individual, icon="✉️")

            st.subheader("月別連絡数 (個別連絡)")
            all_individual_contacts_df = pd.DataFrame()
            for student_data in associated_students_data:
                student_id = student_data['student_id']
                individual_df = db_read(TABLE_INDIVIDUAL_CONTACTS, student_id=student_id)
                if not individual_df.empty:
                    all_individual_contacts_df = pd.concat([all_individual_contacts_df, individual_df])

            if not all_individual_contacts_df.empty:
                all_individual_contacts_df["timestamp"] = pd.to_datetime(all_individual_contacts_df["timestamp"], errors='coerce')
                all_individual_contacts_df = all_individual_contacts_df.dropna(subset=['timestamp'])
                all_individual_contacts_df["month"] = all_individual_contacts_df["timestamp"].dt.to_period("M")
                monthly_counts = all_individual_contacts_df["month"].value_counts().sort_index()
                if not monthly_counts.empty:
                    st.bar_chart(monthly_counts)
                else:
                    st.info("月別連絡データを表示できません。", icon="ℹ️")
            else:
                st.info("個別連絡データがありません。", icon="ℹ️")

    # --- 保護者画面 ---
    elif user_role == 'parent':
        st.sidebar.subheader("保護者メニュー")
        menu_selection = st.sidebar.radio(
            "機能を選択", ["自分の連絡帳", "返信作成", "カレンダー"]
        )

        if len(associated_students_data) > 1:
            selected_student_name = st.sidebar.selectbox("お子さんを選択", student_names_only, key="parent_student_select")
        elif associated_students_data:
            selected_student_name = student_names_only[0]
        else:
            st.error("紐付けられた生徒情報がありません。", icon="❌")
            st.stop()

        selected_student_id = None
        selected_student_class = None
        if selected_student_name:
            for student_data in associated_students_data:
                if student_data['student_name'] == selected_student_name:
                    selected_student_id = student_data['student_id']
                    selected_student_class = student_data.get(STUDENT_CLASS_COLUMN)
                    break
            if selected_student_id is None:
                st.error(f"生徒 '{selected_student_name}' のIDが見つかりません。生徒情報テーブルを確認してください。", icon="❌")
                st.stop()
        st.sidebar.info(f"連絡帳: {selected_student_name}", icon="👨‍👩‍👧‍👦")

        if menu_selection == "自分の連絡帳":
            st.header(f"{selected_student_name} 連絡帳")
            st.subheader("📢 全体連絡")
            if not general_df.empty:
                general_df_display = general_df.copy()
                general_df_display["timestamp"] = pd.to_datetime(general_df_display["timestamp"])
                general_df_display = general_df_display.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                for index, row in general_df_display.iterrows():
                    with st.expander(f"📅 {row['contact_date'].strftime('%Y/%m/%d')} - {row['sender']} (全体連絡)", expanded=False):
                        st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                        st.info(f"**連絡内容:** {row['message']}")
                        if row['items_notice']:
                            st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                        st.markdown("---")
            else:
                st.info("全体連絡はまだありません。", icon="ℹ️")

            st.subheader(f"🧑‍🏫 {selected_student_name} への個別連絡")
            # 個別連絡はSession Stateに保持せず、都度DBから読み込む
            individual_df = db_read(TABLE_INDIVIDUAL_CONTACTS, student_id=selected_student_id)
            if not individual_df.empty:
                individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"])
                individual_df = individual_df.sort_values(by="timestamp", ascending=False).reset_index(drop=True)

                for index, row in individual_df.iterrows():
                    with st.expander(f"📅 {row['contact_date'].strftime('%Y/%m/%d')} - {row['sender']}", expanded=False):
                        st.write(f"**送信日時:** {row['timestamp'].strftime('%Y/%m/%d %H:%M:%S')}")
                        st.info(f"**学校からの連絡:** {row['message']}")
                        if row['home_reply']:
                            st.success(f"**あなたの返信:** {row['home_reply']}")
                        if row['items_notice']:
                            st.warning(f"**持ち物・特記事項:** {row['items_notice']}")
                        st.markdown("---")
            else:
                st.info(f"{selected_student_name} への個別連絡はまだありません。", icon="ℹ️")

        elif menu_selection == "返信作成":
            st.header(f"{selected_student_name} からの返信作成")
            st.info("返信したい個別連絡を選択してください。", icon="ℹ️")
            # 個別連絡はSession Stateに保持せず、都度DBから読み込む
            individual_df = db_read(TABLE_INDIVIDUAL_CONTACTS, student_id=selected_student_id)
            if not individual_df.empty:
                individual_df["timestamp"] = pd.to_datetime(individual_df["timestamp"])
                individual_df = individual_df.dropna(subset=['timestamp'])
                reply_needed_df = individual_df[
                    (individual_df["home_reply"].astype(str).str.strip() == "")
                ]

                if not reply_needed_df.empty:
                    latest_unreplied = reply_needed_df.sort_values(by="timestamp", ascending=False).iloc[0]
                    st.subheader(f"返信対象連絡: {latest_unreplied['contact_date'].strftime('%Y/%m/%d')} の学校からの連絡")
                    st.info(latest_unreplied['message'])

                    with st.form("reply_form", clear_on_submit=True):
                        home_reply = st.text_area("学校への返信内容", height=150, placeholder="先生への返信を入力してください。")
                        submitted_reply = st.form_submit_button("返信を送信")

                        if submitted_reply:
                            if not home_reply.strip():
                                st.error("返信内容は必須です。", icon="❌")
                            else:
                                data_to_update = {"home_reply": home_reply}
                                if db_update(TABLE_INDIVIDUAL_CONTACTS, latest_unreplied['id'], data_to_update):
                                    st.success("返信を送信しました！", icon="✅")
                                    st.balloons()
                                    st.rerun() # 表示を更新するために再実行
                                else:
                                    st.error("返信の保存に失敗しました。", icon="❌")
                else:
                    st.info("返信する未返信の個別連絡はありません。", icon="ℹ️")
            else:
                st.info("個別連絡データがありません。", icon="ℹ️")

        elif menu_selection == "カレンダー":
            st.header("カレンダー (行事予定・配布物)")
            if not calendar_df_full.empty:
                st.subheader("今後の予定")
                # 保護者の場合、自分の子どものクラスに関連するイベントと「全体」のイベントをフィルタリング
                parent_display_events = calendar_df_full[
                    calendar_df_full['target_classes'].fillna('').apply(
                        lambda x: not x or "全体" in [c.strip() for c in x.split(',')] or (selected_student_class and selected_student_class in [c.strip() for c in x.split(',')])
                    )
                ]
                today = datetime.now().date()
                upcoming_events = parent_display_events[parent_display_events['event_date'].dt.date >= today]

                if not upcoming_events.empty:
                    upcoming_events = upcoming_events.sort_values(by='event_date') # 日付でソート
                    for index, event in upcoming_events.iterrows():
                        event_date_obj = event['event_date']
                        if pd.isna(event_date_obj):
                            st.warning(f"カレンダーイベント '{event.get('event_name', '不明なイベント')}' に無効な日付が含まれています。", icon="⚠️")
                            continue
                        target_classes_info = f" ({event['target_classes']})" if event['target_classes'] else ""
                        st.markdown(f"**{event_date_obj.strftime('%Y/%m/%d')}**: **{event['event_name']}**{target_classes_info} - {event['description']}")
                        st.markdown("---")
                else:
                    st.info("今後のイベントはありません。", icon="ℹ️")
            else:
                st.info("カレンダーデータが読み込めませんでした。", icon="ℹ️")

if __name__ == "__main__":
    main()