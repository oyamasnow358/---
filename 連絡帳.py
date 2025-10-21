def get_service_account_info():
    """
    Streamlit Secretsまたは専用ファイルからGspreadサービスアカウント情報を取得
    Renderでは .streamlit/GSPRED_SECRETS.TOML として配置することを想定
    """
    # まず、st.secretsにgspread_service_accountが存在するか確認（Streamlit Cloud互換性のため）
    if "gspread_service_account" in st.secrets:
        st.sidebar.info("Gspreadサービスアカウント情報をst.secretsから読み込みます。")
        sa_info = st.secrets["gspread_service_account"]
    else:
        # st.secretsに存在しない場合、Secret Fileから直接読み込む
        secrets_file_path = ".streamlit/GSPRED_SECRETS.TOML"
        try:
            # RenderのSecret Filesは絶対パスではなく相対パスで指定される
            # os.path.join(os.getcwd(), secrets_file_path) で現在ディレクトリからの相対パスを構築
            full_path = os.path.join(os.getcwd(), secrets_file_path)
            st.sidebar.info(f"Gspreadサービスアカウント情報をファイル '{full_path}' から読み込みます。")
            with open(full_path, "r") as f:
                # toml.load() は直接辞書を返す
                raw_secrets = toml.load(f)
                sa_info = raw_secrets["gspread_service_account"]
        except FileNotFoundError:
            st.error(f"エラー: Gspreadサービスアカウントファイル '{secrets_file_path}' が見つかりません。")
            st.error("RenderのSecret Filesに `./.streamlit/GSPRED_SECRETS.TOML` として正しく設定されているか確認してください。")
            st.stop()
        except toml.TomlDecodeError as e:
            st.error(f"エラー: GSPRED_SECRETS.TOML の解析に失敗しました: {e}")
            st.error("TOMLファイルのフォーマットが正しいか、特に private_key の改行文字 '\\n' が適切か確認してください。")
            st.stop()
        except KeyError:
            st.error("エラー: GSPRED_SECRETS.TOML ファイル内に '[gspread_service_account]' セクションが見つかりません。")
            st.stop()
        except Exception as e:
            st.error(f"Gspreadサービスアカウント情報の読み込み中に予期せぬエラーが発生しました: {e}")
            st.exception(e)
            st.stop()
            
    # private_keyの改行文字を処理
    if "private_key" in sa_info:
        sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
            
    return sa_info