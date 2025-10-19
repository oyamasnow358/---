import streamlit as st
import gspread

# Secretsから設定を読み込む（ここでは仮の値）
# 実際には.streamlit/secrets.tomlに設定
st.secrets["gspread_service_account"] = {
    "type": "service_account",
    "project_id": "your-project-id",
    "private_key_id": "your-private-key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
    "client_email": "your-service-account-email@your-project-id.iam.gserviceaccount.com",
    "client_id": "your-client-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/...",
    "universe_domain": "googleapis.com"
}

@st.cache_resource(ttl=3600)
def get_gspread_client():
    try:
        service_account_info = st.secrets["gspread_service_account"]
        # print("Service Account Info:", service_account_info) # ターミナルで確認
        gc = gspread.service_account_from_dict(service_account_info)
        return gc
    except Exception as e:
        st.error(f"Gspreadクライアントの初期化に失敗しました: {e}")
        st.exception(e)
        return None

def load_sheet_data_test(spreadsheet_id, worksheet_name="シート1"):
    gc = get_gspread_client()
    if gc is None:
        st.error("Gspreadクライアントが初期化できませんでした。")
        return None
    try:
        spreadsheet = gc.open_by_id(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        st.success(f"スプレッドシートID '{spreadsheet_id}' のデータを正常に読み込みました。")
        st.write(data[:5]) # 最初の5行を表示
        return data
    except Exception as e:
        st.error(f"スプレッドシートID '{spreadsheet_id}' の読み込み中にエラーが発生しました: {e}")
        st.exception(e)
        return None

if __name__ == "__main__":
    st.title("Gspreadテスト")
    
    test_sheet_id = "1y0KuXYI7trE2-lpmVjyG1HDxxAeWEeY_iXmpmQYk_L8" # teachers_sheet_id
    load_sheet_data_test(test_sheet_id)

    test_sheet_id_2 = "1RxtSPxnCwxRnqz7zAezmN8FGgep6FtIx0K99l525q08" # students_sheet_id
    load_sheet_data_test(test_sheet_id_2)