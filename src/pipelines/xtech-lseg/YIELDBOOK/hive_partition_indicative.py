import polars as pl
import pandas as pd
import os
from pathlib import Path
import json

def process_indicative_data_to_hive(results_df, output_base_path="/Volumes/seb's ssd/Work/datastore/yieldbook/indicative"):
    """
    Process indicative data and write to Hive-style partitioned folders by ISIN.
    
    Args:
        results_df: pandas DataFrame with 'indic' column containing dict data
        output_base_path: Base path for output directory
    """
    
    print(f"Processing {len(results_df)} records...")
    
    # Create output directory
    os.makedirs(output_base_path, exist_ok=True)
    
    # Filter out rows with None ISINs and save excluded ISINs
    excluded_isins = []
    original_query_isins = []
    
    # Check for None ISINs and collect them
    none_mask = results_df['isin'].isna() | (results_df['isin'] == 'None') | results_df['isin'].isnull()
    if none_mask.any():
        excluded_rows = results_df[none_mask]
        print(f"Found {len(excluded_rows)} records with None ISINs")
        
        # Extract original query ISINs from excluded rows if available
        for idx, row in excluded_rows.iterrows():
            # Try to get original ISIN from various possible sources
            original_isin = None
            if 'original_isin' in row:
                original_isin = row['original_isin']
            elif 'query_isin' in row:
                original_isin = row['query_isin']
            elif hasattr(row, 'name'):  # If index contains the original ISIN
                original_isin = row.name
            
            excluded_isins.append({
                'original_isin': original_isin,
                'diagnostic': row.get('diagnostic', 'Security not found'),
                'excluded_reason': 'ISIN is None'
            })
        
        # Save excluded ISINs to file
        excluded_file = os.path.join(output_base_path, "excluded_isins.json")
        
        # Load existing excluded ISINs if file exists
        existing_excluded = []
        if os.path.exists(excluded_file):
            try:
                with open(excluded_file, 'r') as f:
                    existing_excluded = json.load(f)
            except:
                existing_excluded = []
        
        # Append new excluded ISINs
        all_excluded = existing_excluded + excluded_isins
        
        with open(excluded_file, 'w') as f:
            json.dump(all_excluded, f, indent=2)
        
        print(f"Saved {len(excluded_isins)} excluded ISINs to {excluded_file}")
        
        # Filter out None ISINs from processing
        results_df = results_df[~none_mask].copy()
        print(f"Continuing processing with {len(results_df)} valid records")
    
    # 1) Base columns (drop the big dict for now)
    base_cols = ['isin', 'cusip', 'ticker', 'country', 'currency', 'identifier', 
                 'description', 'issuerTicker', 'maturityDate', 'securityType', 
                 'currentCoupon', 'securitySubType']
    
    # Filter to only include columns that exist in the DataFrame
    existing_base_cols = [col for col in base_cols if col in results_df.columns]
    base = pl.from_pandas(results_df[existing_base_cols])
    
    # 2) Flatten top-level keys from `indic` 
    print("Flattening indicative data...")
    indic_top = pl.from_pandas(
        pd.json_normalize(results_df["indic"])
    ).rename(lambda c: f"indic.{c}")
    
    # 3) Select key indicative fields to keep (adjust based on your needs)
    keep_fields = [
        "indic.indexRating", "indic.issuerCountry", "indic.industryCode", "indic.industrySubCode",
        "indic.cgmiSectorCode", "indic.seniorityType", "indic.callFlag", "indic.putFlag",
        "indic.issueDate", "indic.issueAmount", "indic.outstandingAmount", "indic.marketType",
        "indic.modifiedTimeStamp", "indic.issuerName.value", "indic.issuerName.language",
        "indic.debtClassCode", "indic.assetClassCode", "indic.vPointType", "indic.securityCalcType",
        "indic.paymentFreq", "indic.dayCount", "indic.issuePrice", "indic.issueYield",
        "indic.issueSpread", "indic.minimumPiece", "indic.redemptionValue", "indic.firstCouponDate",
        "indic.finalMaturityDate", "indic.outstandingDate", "indic.datedDate",
        "indic.highestRating", "indic.middleRating", "indic.lowestRating", "indic.lowerRating",
        "indic.issuerHighestRating", "indic.issuerMiddleRating", "indic.issuerLowestRating",
        "indic.industryDescription", "indic.industrySubDescription", "indic.debtClassDescription",
        "indic.cgmiSectorDescription", "indic.assetClassSubDescription", "indic.parentDescription",
        "indic.bloombergTicker", "indic.cmaTicker", "indic.parentTicker",
        "indic.greenBondFlag", "indic.esgBondFlag", "indic.makeWholeFlag", "indic.securedFlag",
        "indic.inDefaultFlag", "indic.currentHighYieldFlag", "indic.originalHighYieldFlag",
        "indic.fallenAngelFlag", "indic.risingStarFlag", "indic.leveragedBuyoutFlag",
        "indic.chapter11Flag", "indic.privatePlacementFlag", "indic.p144AFlag", "indic.regSFlag",
        "indic.sinkFlag", "indic.euroCallFlag", "indic.deliveryFlag", "indic.extendFlag",
        "indic.sedol", "indic.sedol7", "indic.permID", "indic.commonCode", "indic.source",
        "indic.cfi", "indic.ric", "indic.wkn", "indic.figi"
    ]
    
    # Filter to only include fields that exist in the flattened data
    available_fields = [field for field in keep_fields if field in indic_top.columns]
    
    # 4) Combine base + selected indic fields
    if available_fields:
        flat = pl.concat([base, indic_top.select(available_fields)], how="horizontal")
    else:
        flat = base
        print("Warning: No indicative fields found to flatten")
    
    # 5) Process nested structures separately
    
    # Ratings history: explode the list of dicts
    print("Processing ratings history...")
    ratings_data = []
    for idx, row in results_df.iterrows():
        isin = row["isin"]
        cusip = row["cusip"]
        moody_ratings = row["indic"].get("moody", [])
        
        for rating in moody_ratings:
            ratings_data.append({
                "isin": isin,
                "cusip": cusip,
                "rating": rating.get("value"),
                "effectiveDate": rating.get("effectiveDate"),
                "expirationDate": rating.get("expirationDate"),
                "agency": "Moody"
            })
    
    if ratings_data:
        ratings = pl.DataFrame(ratings_data)
    else:
        # Create empty DataFrame with correct schema
        ratings = pl.DataFrame({
            "isin": [],
            "cusip": [],
            "rating": [],
            "effectiveDate": [],
            "expirationDate": [],
            "agency": []
        })
    
    # 6) Underwriters
    print("Processing underwriters...")
    uw_data = []
    for idx, row in results_df.iterrows():
        isin = row["isin"]
        cusip = row["cusip"]
        underwriters = row["indic"].get("dataUnderwriterList", [])
        
        for uw in underwriters:
            uw_data.append({
                "isin": isin,
                "cusip": cusip,
                "underwriter": uw.get("name"),
                "rank": uw.get("rank"),
                "split": uw.get("split")
            })
    
    if uw_data:
        uw = pl.DataFrame(uw_data)
    else:
        # Create empty DataFrame with correct schema
        uw = pl.DataFrame({
            "isin": [],
            "cusip": [],
            "underwriter": [],
            "rank": [],
            "split": []
        })
    
    # 7) ESG Scores (if available)
    print("Processing ESG scores...")
    esg_data = []
    for idx, row in results_df.iterrows():
        isin = row["isin"]
        cusip = row["cusip"]
        esg_scores = row["indic"].get("corporateESGScore", {})
        
        if esg_scores:
            esg_record = {"isin": isin, "cusip": cusip}
            esg_record.update(esg_scores)
            esg_data.append(esg_record)
    
    if esg_data:
        esg = pl.DataFrame(esg_data)
    else:
        # Create empty DataFrame with correct schema
        esg = pl.DataFrame({
            "isin": [],
            "cusip": [],
            "esgenvScore": [],
            "esggovScore": [],
            "esgsocScore": [],
            "esgglobalScore": []
        })
    
    # 8) FRTB data (if available)
    print("Processing FRTB data...")
    frtb_data = []
    for idx, row in results_df.iterrows():
        isin = row["isin"]
        cusip = row["cusip"]
        frtb_info = row["indic"].get("frtb", {})
        
        if frtb_info:
            frtb_record = {
                "isin": isin,
                "cusip": cusip,
                "frtb_sector": frtb_info.get("sector", {}).get("value"),
                "frtb_riskWeight": frtb_info.get("riskWeight"),
                "frtb_bucketNumber": frtb_info.get("bucketNumber"),
                "frtb_creditQuality": frtb_info.get("creditQuality"),
                "frtb_riskClassification": frtb_info.get("riskClassification")
            }
            frtb_data.append(frtb_record)
    
    if frtb_data:
        frtb = pl.DataFrame(frtb_data)
    else:
        # Create empty DataFrame with correct schema
        frtb = pl.DataFrame({
            "isin": [],
            "cusip": [],
            "frtb_sector": [],
            "frtb_riskWeight": [],
            "frtb_bucketNumber": [],
            "frtb_creditQuality": [],
            "frtb_riskClassification": []
        })
    
    # 9) Write to Hive-style partitioned folders by CUSIP
    print("Writing partitioned data...")
    
    # Get unique CUSIPs
    unique_isins = flat["isin"].unique().to_list()
    
    for isin in unique_isins:
        isin_dir = os.path.join(output_base_path, f"isin={isin}")
        os.makedirs(isin_dir, exist_ok=True)
        
        # Filter data for this CUSIP
        isin_flat = flat.filter(pl.col("isin") == isin)
        isin_ratings = ratings.filter(pl.col("isin") == isin) if len(ratings) > 0 else ratings
        isin_uw = uw.filter(pl.col("isin") == isin) if len(uw) > 0 else uw
        isin_esg = esg.filter(pl.col("isin") == isin) if len(esg) > 0 else esg
        isin_frtb = frtb.filter(pl.col("isin") == isin) if len(frtb) > 0 else frtb
        
        # Write parquet files with ZSTD compression
        isin_flat.write_parquet(
            os.path.join(isin_dir, "securities.parquet"), 
            compression="zstd", 
            statistics=True
        )
        
        isin_ratings.write_parquet(
            os.path.join(isin_dir, "ratings_history.parquet"), 
            compression="zstd", 
            statistics=True
        )
        
        isin_uw.write_parquet(
            os.path.join(isin_dir, "underwriters.parquet"), 
            compression="zstd", 
            statistics=True
        )
        
        isin_esg.write_parquet(
            os.path.join(isin_dir, "esg_scores.parquet"), 
            compression="zstd", 
            statistics=True
        )
        
        isin_frtb.write_parquet(
            os.path.join(isin_dir, "frtb_data.parquet"), 
            compression="zstd", 
            statistics=True
        )
    
    print(f"Successfully wrote data for {len(unique_isins)} ISINs to {output_base_path}")
    
    return {
        "securities": flat,
        "ratings": ratings,
        "underwriters": uw,
        "esg_scores": esg,
        "frtb_data": frtb,
        "output_path": output_base_path,
        "isins_processed": unique_isins
    }


def query_examples():
    """
    Example queries for the partitioned data using Polars lazy evaluation
    """
    base_path = "/Volumes/seb's ssd/Work/datastore/yieldbook/indicative"
    
    # Example 1: Query specific CUSIP
    isin = "00037BAC6"
    isin_path = os.path.join(base_path, f"isin={isin}")
    
    if os.path.exists(isin_path):
        securities = pl.scan_parquet(os.path.join(isin_path, "securities.parquet"))
        ratings = pl.scan_parquet(os.path.join(isin_path, "ratings_history.parquet"))
        
        print(f"Securities for ISIN {isin}:")
        print(securities.collect())
        
        print(f"\nRatings history for ISIN {isin}:")
        print(ratings.collect())
    
    # Example 2: Query across all securities (using consolidated files)
    consolidated_path = os.path.join(base_path, "_consolidated")
    
    if os.path.exists(consolidated_path):
        all_securities = pl.scan_parquet(os.path.join(consolidated_path, "all_securities.parquet"))
        
        # High yield bonds example
        high_yield = all_securities.filter(
            pl.col("indic.indexRating").is_in(["Ba1", "Ba2", "Ba3", "B1", "B2", "B3", "Caa", "Ca", "C"])
        )
        
        print("\nHigh yield bonds:")
        print(high_yield.collect())
        
        # Investment grade bonds
        investment_grade = all_securities.filter(
            pl.col("indic.indexRating").is_in(["Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3", "Baa1", "Baa2", "Baa3"])
        )
        
        print("\nInvestment grade bonds count:")
        print(investment_grade.select(pl.count()).collect())


