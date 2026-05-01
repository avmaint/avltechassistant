import pandas as pd
import numpy as np

def inspect_data():
    try:
        df_cables = pd.read_excel("../data/uac_cables.xlsx", sheet_name="Cables")
        
        # Normalize for searching
        df_cables['TagNorm'] = df_cables['Tag'].astype(str).str.strip().str.upper()
        df_cables['SrcTagNorm'] = df_cables['SrcTag'].astype(str).str.strip().str.upper()
        df_cables['DstTagNorm'] = df_cables['DstTag'].astype(str).str.strip().str.upper()
        
        # Target assets
        target_tags = ["2410-1607", "ZVKU-A001", "ZVIU-A006"]
        target_tags_norm = [t.upper() for t in target_tags]
        
        print("--- Cables involving target tags ---")
        mask = (df_cables['SrcTagNorm'].isin(target_tags_norm) | 
                df_cables['DstTagNorm'].isin(target_tags_norm))
        
        relevant_cables = df_cables[mask]
        print(relevant_cables[['Tag', 'SrcTag', 'SrcPort', 'DstTag', 'DstPort', 'Type', 'Protocol']].to_string())
        
        print("\n--- Route cables for ZVKU-A001 ---")
        route_mask = (df_cables['SrcTagNorm'] == "ZVKU-A001") & (df_cables['DstTagNorm'] == "ZVKU-A001")
        print(df_cables[route_mask][['Tag', 'SrcTag', 'SrcPort', 'DstTag', 'DstPort', 'Type', 'Protocol']].to_string())

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_data()
