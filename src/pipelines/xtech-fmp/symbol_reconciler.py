"""
Stock Symbol and Company Name Reconciliation Module

This module provides comprehensive reconciliation between different data sources
containing stock symbols and company names. It handles different symbol conventions,
company name variations, and provides confidence-scored matching.

Usage:
    from symbol_reconciler import CompanyNameMatcher
    
    matcher = CompanyNameMatcher()
    exact_matches, cross_matches, unmatched = matcher.reconcile_sources(
        source_a, source_b,
        symbol_col_a='symbol', name_col_a='issuer_name',
        symbol_col_b='symbol', name_col_b='companyName'
    )
"""

import pandas as pd
import unicodedata
import re
from typing import Tuple, Dict, List, Optional, Literal
from rapidfuzz import fuzz, process
from cleanco import basename
from tqdm import tqdm


class CompanyNameMatcher:
    """
    A class for matching and reconciling company names and stock symbols
    across different data sources.
    """
    
    def __init__(self, 
                 high_confidence_threshold: float = 90.0,
                 medium_confidence_threshold: float = 80.0,
                 low_confidence_threshold: float = 70.0):
        """
        Initialize the matcher with confidence thresholds.
        
        Args:
            high_confidence_threshold: Score above which matches are auto-accepted
            medium_confidence_threshold: Score for flagging manual review
            low_confidence_threshold: Minimum score to consider a match
        """
        self.high_threshold = high_confidence_threshold
        self.medium_threshold = medium_confidence_threshold
        self.low_threshold = low_confidence_threshold
        
        # Common business terms to remove (beyond cleanco)
        self.common_terms = {
            'holding', 'holdings', 'group', 'company', 
            'international', 'global', 'industries', 
            'management', 'asset', 'investment', 'investments'
        }
    
    def normalize_company_name(self, name: str) -> str:
        """
        Normalize company name for comparison.
        
        Steps:
        1. Lowercase conversion
        2. Unicode normalization
        3. Remove punctuation
        4. Strip legal suffixes using cleanco
        5. Remove common business terms
        6. Normalize whitespace
        
        Args:
            name: Raw company name
            
        Returns:
            Normalized company name
            
        Example:
            >>> normalize_company_name("Apple Inc.")
            'apple'
            >>> normalize_company_name("JPMorgan Chase & Co.")
            'jpmorgan chase'
        """
        if pd.isna(name) or not name:
            return ""
        
        # Convert to lowercase
        name = str(name).lower().strip()
        
        # Normalize unicode characters (handle accents, special chars)
        name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
        
        # Remove punctuation and special characters (keep spaces)
        name = re.sub(r'[^\w\s]', ' ', name)
        
        # Use cleanco to remove legal suffixes
        # Run twice to catch nested suffixes (e.g., "Corp. Inc.")
        name = basename(name)
        name = basename(name)
        
        # Remove common business terms
        words = name.split()
        words = [w for w in words if w not in self.common_terms]
        name = ' '.join(words)
        
        # Normalize whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name
    
    def compute_match_score(self, name1: str, name2: str) -> Tuple[float, str]:
        """
        Compare two company names and return confidence score.
        
        Uses multiple fuzzy matching algorithms and returns the maximum score:
        1. token_set_ratio - handles subset matches and word order
        2. token_sort_ratio - handles reordered tokens
        3. ratio - baseline character similarity
        
        Args:
            name1: First company name (raw or normalized)
            name2: Second company name (raw or normalized)
            
        Returns:
            Tuple of (confidence_score, match_method)
            - confidence_score: float between 0-100
            - match_method: name of the algorithm that produced the score
            
        Example:
            >>> compute_match_score("Apple Inc.", "Apple Incorporated")
            (95.0, 'token_set_ratio')
        """
        # Normalize both names
        norm1 = self.normalize_company_name(name1)
        norm2 = self.normalize_company_name(name2)
        
        # Handle empty strings
        if not norm1 or not norm2:
            return 0.0, "empty_string"
        
        # Exact match after normalization
        if norm1 == norm2:
            return 100.0, "exact_match"
        
        # Calculate multiple similarity scores
        scores = {
            'token_set_ratio': fuzz.token_set_ratio(norm1, norm2),
            'token_sort_ratio': fuzz.token_sort_ratio(norm1, norm2),
            'ratio': fuzz.ratio(norm1, norm2)
        }
        
        # Return the maximum score and its method
        best_method = max(scores, key=scores.get)
        best_score = scores[best_method]
        
        return best_score, best_method
    
    def match_symbol_in_both_sources(self,
                                     symbol: str,
                                     name_a: str,
                                     name_b: str) -> Dict:
        """
        Match a symbol that exists in both sources.
        
        Args:
            symbol: The stock symbol
            name_a: Company name from source A
            name_b: Company name from source B
            
        Returns:
            Dictionary with match result:
            {
                'symbol': str,
                'name_a': str,
                'name_b': str,
                'match_score': float,
                'match_method': str,
                'confidence': str,  # 'high', 'medium', 'low', 'no_match'
                'action': str  # 'accept', 'review', 'reject'
            }
        """
        score, method = self.compute_match_score(name_a, name_b)
        
        if score >= self.high_threshold:
            confidence = 'high'
            action = 'accept'
        elif score >= self.medium_threshold:
            confidence = 'medium'
            action = 'review'
        elif score >= self.low_threshold:
            confidence = 'low'
            action = 'review'
        else:
            confidence = 'no_match'
            action = 'reject'
        
        return {
            'symbol': symbol,
            'name_a': name_a,
            'name_b': name_b,
            'match_score': score,
            'match_method': method,
            'confidence': confidence,
            'action': action
        }
    
    def find_best_name_match(self,
                            query_name: str,
                            candidate_df: pd.DataFrame,
                            name_column: str) -> Optional[Dict]:
        """
        Find the best matching company name in a DataFrame.
        
        Args:
            query_name: The company name to match
            candidate_df: DataFrame containing candidate companies
            name_column: Column name containing company names
            
        Returns:
            Dictionary with best match info or None if no good match:
            {
                'matched_index': int,
                'matched_name': str,
                'match_score': float,
                'match_method': str,
                'confidence': str
            }
        """
        if candidate_df.empty:
            return None
        
        # Calculate scores for all candidates
        scores = []
        for idx, row in candidate_df.iterrows():
            candidate_name = row[name_column]
            score, method = self.compute_match_score(query_name, candidate_name)
            scores.append({
                'index': idx,
                'name': candidate_name,
                'score': score,
                'method': method
            })
        
        # Find best match
        best_match = max(scores, key=lambda x: x['score'])
        
        # Only return if above minimum threshold
        if best_match['score'] >= self.low_threshold:
            if best_match['score'] >= self.high_threshold:
                confidence = 'high'
            elif best_match['score'] >= self.medium_threshold:
                confidence = 'medium'
            else:
                confidence = 'low'
            
            return {
                'matched_index': best_match['index'],
                'matched_name': best_match['name'],
                'match_score': best_match['score'],
                'match_method': best_match['method'],
                'confidence': confidence
            }
        
        return None
    
    def find_best_name_matches_bulk(self,
                                   query_names: List[str],
                                   candidate_df: pd.DataFrame,
                                   name_column: str) -> List[Optional[Dict]]:
        """
        Find best matching company names for multiple queries at once (vectorized).
        Much faster than calling find_best_name_match repeatedly.
        
        Args:
            query_names: List of company names to match
            candidate_df: DataFrame containing candidate companies
            name_column: Column name containing company names
            
        Returns:
            List of match dictionaries (one per query), None for no match
        """
        if candidate_df.empty:
            return [None] * len(query_names)
        
        # Normalize all candidate names once
        candidates = candidate_df[name_column].tolist()
        normalized_candidates = [self.normalize_company_name(c) for c in candidates]
        
        results = []
        for query_name in query_names:
            norm_query = self.normalize_company_name(query_name)
            
            if not norm_query:
                results.append(None)
                continue
            
            # Use rapidfuzz's process.extractOne for fast matching
            # Try token_set_ratio first (best for company names)
            best_match = process.extractOne(
                norm_query,
                normalized_candidates,
                scorer=fuzz.token_set_ratio,
                score_cutoff=self.low_threshold
            )
            
            if best_match:
                matched_text, score, idx = best_match
                
                if score >= self.high_threshold:
                    confidence = 'high'
                elif score >= self.medium_threshold:
                    confidence = 'medium'
                else:
                    confidence = 'low'
                
                results.append({
                    'matched_index': candidate_df.index[idx],
                    'matched_name': candidates[idx],
                    'match_score': score,
                    'match_method': 'token_set_ratio',
                    'confidence': confidence
                })
            else:
                results.append(None)
        
        return results
    
    def reconcile_sources(self,
                         source_a: pd.DataFrame,
                         source_b: pd.DataFrame,
                         symbol_col_a: str,
                         name_col_a: str,
                         symbol_col_b: str,
                         name_col_b: str,
                         process_mode: Literal['both', 'only_a', 'only_b', 'common_only'] = 'both') -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Reconcile two data sources with symbols and company names.
        
        Args:
            source_a: DataFrame for source A
            source_b: DataFrame for source B  
            symbol_col_a: Symbol column name in source A
            name_col_a: Company name column in source A
            symbol_col_b: Symbol column name in source B
            name_col_b: Company name column in source B
            process_mode: Which stages to process:
                - 'both': Process all stages (common, only_a, only_b)
                - 'only_a': Only process common symbols and symbols only in A
                - 'only_b': Only process common symbols and symbols only in B
                - 'common_only': Only process symbols in both sources
            
        Returns:
            Tuple of three DataFrames:
            1. exact_matches: Symbols in both sources with name validation
            2. cross_matches: Symbols in one source matched to different symbol in other
            3. unmatched: Symbols that couldn't be matched
        """
        # Normalize symbols for comparison (uppercase, strip whitespace)
        source_a[f'{symbol_col_a}_norm'] = source_a[symbol_col_a].str.upper().str.strip()
        source_b[f'{symbol_col_b}_norm'] = source_b[symbol_col_b].str.upper().str.strip()
        
        # Find symbols in both sources
        symbols_a = set(source_a[f'{symbol_col_a}_norm'].dropna())
        symbols_b = set(source_b[f'{symbol_col_b}_norm'].dropna())
        
        common_symbols = symbols_a & symbols_b
        only_in_a = symbols_a - symbols_b
        only_in_b = symbols_b - symbols_a
        
        exact_matches = []
        cross_matches = []
        unmatched = []
        
        print(f"\n{'='*60}")
        print(f"Symbol Reconciliation Progress")
        print(f"{'='*60}")
        
        # Stage 1: Process symbols in both sources
        print(f"\nStage 1: Processing {len(common_symbols)} common symbols...")
        for symbol in tqdm(list(common_symbols), desc="Common symbols", unit="symbol"):
            row_a = source_a[source_a[f'{symbol_col_a}_norm'] == symbol].iloc[0]
            row_b = source_b[source_b[f'{symbol_col_b}_norm'] == symbol].iloc[0]
            
            match_result = self.match_symbol_in_both_sources(
                symbol,
                row_a[name_col_a],
                row_b[name_col_b]
            )
            
            match_result.update({
                'symbol_a': row_a[symbol_col_a],
                'symbol_b': row_b[symbol_col_b],
                'source': 'both'
            })
            
            exact_matches.append(match_result)
        
        # Stage 2: Process symbols only in source A
        if process_mode in ['both', 'only_a']:
            print(f"\nStage 2: Processing {len(only_in_a)} symbols only in source A...")
            
            # Get all rows for symbols only in A
            rows_a = source_a[source_a[f'{symbol_col_a}_norm'].isin(only_in_a)]
            names_a = rows_a[name_col_a].tolist()
            
            # Bulk match all names at once (much faster)
            print("  Finding best matches in source B...")
            best_matches = self.find_best_name_matches_bulk(names_a, source_b, name_col_b)
            
            # Process results with progress bar
            for (idx, row_a), best_match in tqdm(
                zip(rows_a.iterrows(), best_matches), 
                total=len(rows_a),
                desc="Only in A", 
                unit="symbol"
            ):
                name_a = row_a[name_col_a]
                
                if best_match and best_match['confidence'] in ['high', 'medium']:
                    matched_row_b = source_b.loc[best_match['matched_index']]
                    cross_matches.append({
                        'symbol_a': row_a[symbol_col_a],
                        'symbol_b': matched_row_b[symbol_col_b],
                        'name_a': name_a,
                        'name_b': best_match['matched_name'],
                        'match_score': best_match['match_score'],
                        'match_method': best_match['match_method'],
                        'confidence': best_match['confidence'],
                        'action': 'accept' if best_match['confidence'] == 'high' else 'review',
                        'source': 'only_in_a'
                    })
                else:
                    unmatched.append({
                        'symbol': row_a[symbol_col_a],
                        'name': name_a,
                        'source': 'only_in_a',
                        'reason': 'no_name_match_in_b'
                    })
        else:
            print(f"\nStage 2: Skipping {len(only_in_a)} symbols only in source A (process_mode={process_mode})")
            # Add all to unmatched
            rows_a = source_a[source_a[f'{symbol_col_a}_norm'].isin(only_in_a)]
            for idx, row_a in rows_a.iterrows():
                unmatched.append({
                    'symbol': row_a[symbol_col_a],
                    'name': row_a[name_col_a],
                    'source': 'only_in_a',
                    'reason': 'skipped_by_process_mode'
                })
        
        # Stage 3: Process symbols only in source B
        if process_mode in ['both', 'only_b']:
            print(f"\nStage 3: Processing {len(only_in_b)} symbols only in source B...")
            
            # Get all rows for symbols only in B
            rows_b = source_b[source_b[f'{symbol_col_b}_norm'].isin(only_in_b)]
            names_b = rows_b[name_col_b].tolist()
            
            # Bulk match all names at once (much faster)
            print("  Finding best matches in source A...")
            best_matches = self.find_best_name_matches_bulk(names_b, source_a, name_col_a)
            
            # Process results with progress bar
            for (idx, row_b), best_match in tqdm(
                zip(rows_b.iterrows(), best_matches),
                total=len(rows_b),
                desc="Only in B",
                unit="symbol"
            ):
                name_b = row_b[name_col_b]
                
                if best_match and best_match['confidence'] in ['high', 'medium']:
                    matched_row_a = source_a.loc[best_match['matched_index']]
                    cross_matches.append({
                        'symbol_a': matched_row_a[symbol_col_a],
                        'symbol_b': row_b[symbol_col_b],
                        'name_a': best_match['matched_name'],
                        'name_b': name_b,
                        'match_score': best_match['match_score'],
                        'match_method': best_match['match_method'],
                        'confidence': best_match['confidence'],
                        'action': 'accept' if best_match['confidence'] == 'high' else 'review',
                        'source': 'only_in_b'
                    })
                else:
                    unmatched.append({
                        'symbol': row_b[symbol_col_b],
                        'name': name_b,
                        'source': 'only_in_b',
                        'reason': 'no_name_match_in_a'
                    })
        else:
            print(f"\nStage 3: Skipping {len(only_in_b)} symbols only in source B (process_mode={process_mode})")
            # Add all to unmatched
            rows_b = source_b[source_b[f'{symbol_col_b}_norm'].isin(only_in_b)]
            for idx, row_b in rows_b.iterrows():
                unmatched.append({
                    'symbol': row_b[symbol_col_b],
                    'name': row_b[name_col_b],
                    'source': 'only_in_b',
                    'reason': 'skipped_by_process_mode'
                })
        
        print(f"\n{'='*60}")
        print(f"Reconciliation Complete!")
        print(f"{'='*60}\n")
        
        return (
            pd.DataFrame(exact_matches),
            pd.DataFrame(cross_matches),
            pd.DataFrame(unmatched)
        )


def load_source_a(issuer_name_symbol_map: dict) -> pd.DataFrame:
    """
    Load source A data from issuer_name_symbol_map dictionary.
    
    Args:
        issuer_name_symbol_map: Dictionary mapping issuer names to symbols
        
    Returns:
        DataFrame with columns: symbol, issuer_name
    """
    return pd.DataFrame(issuer_name_symbol_map)


def load_source_b(parquet_path: str) -> pd.DataFrame:
    """
    Load source B data from FMP parquet file.
    
    Args:
        parquet_path: Path to the parquet file
        
    Returns:
        DataFrame with columns: symbol, companyName, and other fields
    """
    return pd.read_parquet(parquet_path)


def main(issuer_name_symbol_map: dict = None,
         source_b_path: str = None,
         output_dir: str = ".") -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Main reconciliation workflow.
    
    Args:
        issuer_name_symbol_map: Dictionary with your existing issuer->symbol mapping
        source_b_path: Path to FMP company profile parquet file
        output_dir: Directory to save output CSV files
    
    Returns:
        Tuple of (exact_matches, cross_matches, unmatched) DataFrames
    """
    # Default paths
    if source_b_path is None:
        source_b_path = (
            "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-fmp/"
            "fundamental/company_profile_bulk/PIT/date=2025-10-22/data.parquet"
        )
    
    # Initialize matcher
    matcher = CompanyNameMatcher(
        high_confidence_threshold=90.0,
        medium_confidence_threshold=80.0,
        low_confidence_threshold=70.0
    )
    
    # Load data
    print("Loading data sources...")
    
    if issuer_name_symbol_map is None:
        print("Warning: No issuer_name_symbol_map provided. Using empty DataFrame.")
        source_a = pd.DataFrame(columns=['symbol', 'issuer_name'])
    else:
        source_a = load_source_a(issuer_name_symbol_map)
    
    source_b = load_source_b(source_b_path)
    
    print(f"Source A: {len(source_a)} records")
    print(f"Source B: {len(source_b)} records")
    
    # Reconcile the sources
    print("\nStarting reconciliation...")
    exact_matches, cross_matches, unmatched = matcher.reconcile_sources(
        source_a=source_a,
        source_b=source_b,
        symbol_col_a='symbol',
        name_col_a='issuer_name',
        symbol_col_b='symbol',
        name_col_b='companyName'
    )
    
    # Review results
    print(f"\n{'='*50}")
    print(f"Reconciliation Summary")
    print(f"{'='*50}")
    print(f"Exact symbol matches: {len(exact_matches)}")
    print(f"Cross-symbol matches: {len(cross_matches)}")
    print(f"Unmatched: {len(unmatched)}")
    
    if len(cross_matches) > 0:
        # High confidence matches that can be auto-accepted
        auto_accept = cross_matches[cross_matches['action'] == 'accept']
        print(f"Auto-accept matches: {len(auto_accept)}")
        
        # Matches requiring manual review
        manual_review = cross_matches[cross_matches['action'] == 'review']
        print(f"Require review: {len(manual_review)}")
    
    # Save results
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    exact_matches_path = os.path.join(output_dir, 'exact_symbol_matches.csv')
    cross_matches_path = os.path.join(output_dir, 'cross_symbol_matches.csv')
    unmatched_path = os.path.join(output_dir, 'unmatched_symbols.csv')
    
    exact_matches.to_csv(exact_matches_path, index=False)
    cross_matches.to_csv(cross_matches_path, index=False)
    unmatched.to_csv(unmatched_path, index=False)
    
    print(f"\nResults saved to:")
    print(f"  - {exact_matches_path}")
    print(f"  - {cross_matches_path}")
    print(f"  - {unmatched_path}")
    
    return exact_matches, cross_matches, unmatched


if __name__ == "__main__":
    # Example usage - you would need to provide your issuer_name_symbol_map
    
    # Example issuer_name_symbol_map structure:
    # issuer_name_symbol_map = {
    #     'issuer_name': ['Apple Inc.', 'Microsoft Corporation', ...],
    #     'symbol': ['AAPL', 'MSFT', ...]
    # }
    
    # For testing without actual data:
    print("To use this module, import it and call main() with your data:")
    print("\nfrom symbol_reconciler import main")
    print("exact, cross, unmatched = main(")
    print("    issuer_name_symbol_map=your_data,")
    print("    source_b_path='path/to/parquet',")
    print("    output_dir='./output'")
    print(")")
