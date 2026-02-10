"""
Ultimate AI Prediction Engine for Lottery Zodiac Prediction

This module implements an advanced prediction engine with 18 independent analysis dimensions
to predict the top 2 most likely Chinese zodiac animals for lottery results.

Analysis Dimensions (100% total weight):

1. Basic Statistics (30%):
   - Long-term Missing Analysis (8%)
   - Short-term Hot Analysis (7%)
   - Cycle Pattern Analysis (8%)
   - Consecutive Opening Penalty (7%)

2. Advanced Mathematics (25%):
   - Markov Chain Transition Probability (10%)
   - Fourier Period Analysis (8%)
   - Bayesian Conditional Probability (7%)

3. Number Properties (20%):
   - Number Hot/Cold Analysis (5%)
   - Tail Trend Analysis (5%)
   - Big/Small Analysis (5%)
   - Odd/Even Analysis (5%)

4. Metaphysical Patterns (15%):
   - Zodiac Relationship Analysis (Liu Chong, San He, Liu He) (5%)
   - Five Elements Analysis (mutual generation/restriction) (5%)
   - Color Wave Analysis (red/blue/green) (5%)

5. Validation & Correction (10%):
   - Monte Carlo Simulation (5%)
   - Repeat Prediction Penalty (3%)
   - Prime/Composite Analysis (2%)
   - Random Perturbation
"""

import random
import logging
from typing import Dict, List, Tuple
from collections import Counter, defaultdict
from datetime import datetime

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logging.warning("NumPy not available. Fourier and Monte Carlo features will be limited.")

logger = logging.getLogger(__name__)


# Zodiac mapping (simplified Chinese)
ZODIAC_NUMBERS = {
    '鼠': [6, 18, 30, 42],
    '牛': [5, 17, 29, 41],
    '虎': [4, 16, 28, 40],
    '兔': [3, 15, 27, 39],
    '龙': [2, 14, 26, 38],
    '蛇': [1, 13, 25, 37, 49],
    '马': [12, 24, 36, 48],
    '羊': [11, 23, 35, 47],
    '猴': [10, 22, 34, 46],
    '鸡': [9, 21, 33, 45],
    '狗': [8, 20, 32, 44],
    '猪': [7, 19, 31, 43]
}

# Traditional to Simplified Chinese mapping
TRADITIONAL_TO_SIMPLIFIED = {
    '龍': '龙',
    '馬': '马',
    '雞': '鸡',
    '豬': '猪'
}

# Reverse mapping: number to zodiac
NUMBER_TO_ZODIAC = {}
for zodiac, numbers in ZODIAC_NUMBERS.items():
    for num in numbers:
        NUMBER_TO_ZODIAC[num] = zodiac

# Zodiac relationships (Liu Chong - Six Clashes)
ZODIAC_LIU_CHONG = {
    '鼠': '马', '牛': '羊', '虎': '猴', '兔': '鸡', '龙': '狗', '蛇': '猪',
    '马': '鼠', '羊': '牛', '猴': '虎', '鸡': '兔', '狗': '龙', '猪': '蛇'
}

# Zodiac relationships (San He - Three Harmonies)
ZODIAC_SAN_HE = {
    '鼠': ['龙', '猴'], '牛': ['蛇', '鸡'], '虎': ['马', '狗'], '兔': ['羊', '猪'],
    '龙': ['鼠', '猴'], '蛇': ['牛', '鸡'], '马': ['虎', '狗'], '羊': ['兔', '猪'],
    '猴': ['鼠', '龙'], '鸡': ['牛', '蛇'], '狗': ['虎', '马'], '猪': ['兔', '羊']
}

# Zodiac relationships (Liu He - Six Harmonies)
ZODIAC_LIU_HE = {
    '鼠': '牛', '牛': '鼠', '虎': '猪', '兔': '狗', '龙': '鸡', '蛇': '猴',
    '马': '羊', '羊': '马', '猴': '蛇', '鸡': '龙', '狗': '兔', '猪': '虎'
}

# Five Elements mapping
ZODIAC_FIVE_ELEMENTS = {
    '鼠': '水', '牛': '土', '虎': '木', '兔': '木',
    '龙': '土', '蛇': '火', '马': '火', '羊': '土',
    '猴': '金', '鸡': '金', '狗': '土', '猪': '水'
}

# Five Elements mutual generation (相生)
ELEMENTS_GENERATE = {
    '木': '火', '火': '土', '土': '金', '金': '水', '水': '木'
}

# Five Elements mutual restriction (相克)
ELEMENTS_RESTRICT = {
    '木': '土', '土': '水', '水': '火', '火': '金', '金': '木'
}

# Random perturbation range for score variation
RANDOM_PERTURBATION_RANGE = 15

# Monte Carlo simulation iterations (trade-off: 1000 for accuracy, 100 for performance)
MONTE_CARLO_ITERATIONS = 100

# Color Wave mapping (49 numbers divided into 3 waves)
# Red wave: historically considered "lucky" numbers in Chinese culture
# Blue wave: numbers divisible by 3
# Green wave: all other numbers
RED_WAVE_NUMBERS = [1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46]

def get_color_wave(num: int) -> str:
    """Get color wave for a number"""
    if num in RED_WAVE_NUMBERS:
        return '红'  # Red
    elif num % 3 == 0:
        return '蓝'  # Blue
    else:
        return '绿'  # Green


class PredictionEngineUltimate:
    """Ultimate AI Prediction Engine with 18 independent analysis dimensions"""
    
    def __init__(self, db_handler):
        """Initialize the prediction engine
        
        Args:
            db_handler: Database handler instance
        """
        self.db = db_handler
        self.all_zodiacs = list(ZODIAC_NUMBERS.keys())
        
    def normalize_zodiac(self, zodiac: str) -> str:
        """Convert traditional Chinese to simplified Chinese
        
        Args:
            zodiac: Zodiac name (can be traditional or simplified)
            
        Returns:
            Simplified Chinese zodiac name
        """
        return TRADITIONAL_TO_SIMPLIFIED.get(zodiac, zodiac)
    
    def predict_top2_zodiac(self, period: int = 300, expect: str = None) -> Dict:
        """
        Predict TOP 2 most likely zodiacs using 18-dimensional comprehensive analysis
        
        Args:
            period: Maximum number of historical periods to analyze (default 300)
            expect: Expected period number for prediction
            
        Returns:
            Dictionary containing top 2 zodiac predictions with scores and analysis
        """
        # Dynamic history range based on expect number
        if expect:
            period_num = int(expect[-3:])  # Get last 3 digits
            ranges = {0: 300, 1: 200, 2: 100, 3: 50, 4: 30}
            dynamic_period = ranges[period_num % 5]
            
            # Use expect + period as random seed for reproducibility
            random.seed(int(expect) * 1000 + dynamic_period)
        else:
            dynamic_period = min(period, 300)  # Cap at 300
            random.seed(int(datetime.now().timestamp()))
        
        # Fetch historical data
        history = self.db.get_history(dynamic_period)
        
        if not history:
            # Random selection if no history
            selected = random.sample(self.all_zodiacs, 2)
            random.seed()  # Reset seed
            return {
                'zodiac1': selected[0],
                'zodiac2': selected[1],
                'numbers1': ZODIAC_NUMBERS[selected[0]],
                'numbers2': ZODIAC_NUMBERS[selected[1]],
                'score1': 50.0,
                'score2': 45.0,
                'analysis': {},
                'period': 0
            }
        
        # Get recent predictions for repeat penalty
        recent_predictions = self._get_recent_predictions(5)
        
        # Calculate comprehensive scores for all zodiacs
        zodiac_scores = {}
        
        for zodiac in self.all_zodiacs:
            score = self._calculate_comprehensive_score(
                history, zodiac, dynamic_period, recent_predictions
            )
            zodiac_scores[zodiac] = score
        
        # Sort by total score and get top 2
        sorted_zodiacs = sorted(
            zodiac_scores.items(), 
            key=lambda x: x[1]['total_score'], 
            reverse=True
        )
        
        top2 = sorted_zodiacs[:2]
        zodiac1, analysis1 = top2[0]
        zodiac2, analysis2 = top2[1]
        
        # Reset random seed
        random.seed()
        
        return {
            'zodiac1': zodiac1,
            'zodiac2': zodiac2,
            'numbers1': ZODIAC_NUMBERS[zodiac1],
            'numbers2': ZODIAC_NUMBERS[zodiac2],
            'score1': analysis1['total_score'],
            'score2': analysis2['total_score'],
            'analysis': {
                zodiac1: analysis1,
                zodiac2: analysis2,
                'all_scores': zodiac_scores
            },
            'period': dynamic_period
        }
    
    def _get_recent_predictions(self, limit: int = 5) -> List[str]:
        """Get recent predicted zodiacs for repeat penalty
        
        Args:
            limit: Number of recent predictions to fetch
            
        Returns:
            List of recently predicted zodiacs
        """
        try:
            recent = self.db.get_prediction_history(limit)
            predictions = []
            for record in recent:
                predictions.extend([
                    self.normalize_zodiac(record.get('predict_zodiac1', '')),
                    self.normalize_zodiac(record.get('predict_zodiac2', ''))
                ])
            return predictions
        except Exception as e:
            logger.warning(f"Failed to get recent predictions: {e}")
            return []
    
    def _calculate_comprehensive_score(
        self, 
        history: List[Dict], 
        zodiac: str, 
        period: int,
        recent_predictions: List[str]
    ) -> Dict:
        """Calculate comprehensive score using all 18 dimensions
        
        Args:
            history: Historical lottery data
            zodiac: Zodiac to analyze
            period: Analysis period
            recent_predictions: Recently predicted zodiacs
            
        Returns:
            Dictionary with all dimension scores and total score
        """
        scores = {}
        
        # === 1. Basic Statistics (30%) ===
        scores['long_term_missing'] = self._score_long_term_missing(history, zodiac, period) * 0.08
        scores['short_term_hot'] = self._score_short_term_hot(history, zodiac) * 0.07
        scores['cycle_pattern'] = self._score_cycle_pattern(history, zodiac, period) * 0.08
        scores['consecutive_penalty'] = self._score_consecutive_penalty(history, zodiac) * 0.07
        
        # === 2. Advanced Mathematics (25%) ===
        scores['markov_chain'] = self._score_markov_chain(history, zodiac) * 0.10
        scores['fourier_analysis'] = self._score_fourier_analysis(history, zodiac) * 0.08
        scores['bayesian_probability'] = self._score_bayesian_probability(history, zodiac) * 0.07
        
        # === 3. Number Properties (20%) ===
        scores['number_hot_cold'] = self._score_number_hot_cold(history, zodiac) * 0.05
        scores['tail_trend'] = self._score_tail_trend(history, zodiac) * 0.05
        scores['big_small'] = self._score_big_small(history, zodiac) * 0.05
        scores['odd_even'] = self._score_odd_even(history, zodiac) * 0.05
        
        # === 4. Metaphysical Patterns (15%) ===
        scores['zodiac_relationship'] = self._score_zodiac_relationship(history, zodiac) * 0.05
        scores['five_elements'] = self._score_five_elements(history, zodiac) * 0.05
        scores['color_wave'] = self._score_color_wave(history, zodiac) * 0.05
        
        # === 5. Validation & Correction (10%) ===
        scores['monte_carlo'] = self._score_monte_carlo(history, zodiac) * 0.05
        scores['repeat_penalty'] = self._score_repeat_penalty(zodiac, recent_predictions) * 0.03
        scores['prime_composite'] = self._score_prime_composite(history, zodiac) * 0.02
        
        # Random perturbation
        scores['random_factor'] = random.uniform(-RANDOM_PERTURBATION_RANGE, RANDOM_PERTURBATION_RANGE)
        
        # Calculate total score
        total_score = sum(scores.values())
        
        scores['total_score'] = total_score
        return scores
    
    # === Basic Statistics Dimensions ===
    
    def _score_long_term_missing(self, history: List[Dict], zodiac: str, period: int) -> float:
        """Long-term missing analysis (8%)
        
        Calculates how long a zodiac hasn't appeared. Longer missing = higher score.
        """
        zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history]
        
        try:
            last_idx = zodiac_list.index(zodiac)
            missing_periods = last_idx
        except ValueError:
            missing_periods = len(zodiac_list)
        
        # Score: 0-100 based on missing periods
        # Expected average: period / 12 ≈ 8.3 periods between appearances
        expected_gap = period / 12
        return min(100.0, (missing_periods / expected_gap) * 50)
    
    def _score_short_term_hot(self, history: List[Dict], zodiac: str) -> float:
        """Short-term hot analysis (7%)
        
        Inverse of hot analysis - favors cold zodiacs in recent 20 periods.
        """
        recent_20 = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history[:20]]
        count = recent_20.count(zodiac)
        
        # Inverse scoring: less frequent = higher score
        if count == 0:
            return 100.0
        else:
            return max(0.0, 100.0 - count * 15)
    
    def _score_cycle_pattern(self, history: List[Dict], zodiac: str, period: int) -> float:
        """Cycle pattern analysis (8%)
        
        Analyzes deviation from expected frequency.
        """
        zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history]
        count = zodiac_list.count(zodiac)
        expected = period / 12
        
        # Favor zodiacs below expected frequency
        if count < expected:
            return min(100.0, ((expected - count) / expected) * 100)
        else:
            return max(0.0, 50.0 - ((count - expected) / expected) * 25)
    
    def _score_consecutive_penalty(self, history: List[Dict], zodiac: str) -> float:
        """Consecutive opening penalty (7%)
        
        Penalizes zodiacs that appeared very recently.
        """
        recent_5 = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history[:5]]
        
        if zodiac in recent_5[:1]:
            return 0.0  # Just appeared, heavy penalty
        elif zodiac in recent_5[1:3]:
            return 30.0  # Appeared 2-3 periods ago
        elif zodiac in recent_5[3:5]:
            return 60.0  # Appeared 4-5 periods ago
        else:
            return 100.0  # Not in recent 5
    
    # === Advanced Mathematics Dimensions ===
    
    def _score_markov_chain(self, history: List[Dict], zodiac: str) -> float:
        """Markov chain transition probability (10%)
        
        Analyzes zodiac transition probabilities (first and second order).
        """
        if len(history) < 2:
            return 50.0
        
        zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history]
        
        # First-order Markov: P(current | previous)
        last_zodiac = zodiac_list[0]
        
        # Count transitions from last_zodiac to each zodiac
        transition_count = 0
        total_transitions = 0
        
        for i in range(len(zodiac_list) - 1):
            if zodiac_list[i] == last_zodiac:
                total_transitions += 1
                if zodiac_list[i + 1] == zodiac:
                    transition_count += 1
        
        if total_transitions == 0:
            # Second-order Markov: P(current | previous two)
            if len(history) >= 2:
                last_two = tuple(zodiac_list[:2])
                second_order_count = 0
                second_order_total = 0
                
                for i in range(len(zodiac_list) - 2):
                    if tuple(zodiac_list[i:i+2]) == last_two:
                        second_order_total += 1
                        if i + 2 < len(zodiac_list) and zodiac_list[i + 2] == zodiac:
                            second_order_count += 1
                
                if second_order_total > 0:
                    probability = second_order_count / second_order_total
                    return probability * 100
            
            return 50.0  # Neutral if no transitions found
        
        probability = transition_count / total_transitions
        return probability * 100
    
    def _score_fourier_analysis(self, history: List[Dict], zodiac: str) -> float:
        """Fourier period analysis (8%)
        
        Uses FFT to detect hidden periodic patterns in zodiac appearances.
        """
        if not NUMPY_AVAILABLE or len(history) < 30:
            # Fallback: simple periodic pattern detection
            return self._fallback_periodic_score(history, zodiac)
        
        try:
            zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history]
            
            # Create binary signal: 1 when zodiac appears, 0 otherwise
            signal = [1 if z == zodiac else 0 for z in zodiac_list]
            
            # Apply FFT
            fft_result = np.fft.fft(signal)
            frequencies = np.fft.fftfreq(len(signal))
            
            # Get magnitude spectrum (ignore DC component)
            magnitudes = np.abs(fft_result[1:len(signal)//2])
            
            if len(magnitudes) == 0:
                return 50.0
            
            # Find dominant frequency
            max_magnitude = np.max(magnitudes)
            
            # Normalize to 0-100 score
            # Higher magnitude indicates stronger periodicity
            score = min(100.0, (max_magnitude / len(signal)) * 300)
            
            return score
            
        except Exception as e:
            logger.debug(f"Fourier analysis failed: {e}")
            return self._fallback_periodic_score(history, zodiac)
    
    def _fallback_periodic_score(self, history: List[Dict], zodiac: str) -> float:
        """Fallback periodic pattern detection without NumPy"""
        zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history[:50]]
        
        # Find all appearances
        appearances = [i for i, z in enumerate(zodiac_list) if z == zodiac]
        
        if len(appearances) < 2:
            return 50.0
        
        # Calculate gaps between appearances
        gaps = [appearances[i+1] - appearances[i] for i in range(len(appearances) - 1)]
        
        if not gaps:
            return 50.0
        
        # Check for periodicity: consistent gaps indicate periodic pattern
        avg_gap = sum(gaps) / len(gaps)
        variance = sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)
        
        # Low variance = high periodicity score
        consistency = max(0.0, 100.0 - variance)
        return consistency
    
    def _score_bayesian_probability(self, history: List[Dict], zodiac: str) -> float:
        """Bayesian conditional probability (7%)
        
        Calculates P(zodiac | conditions) based on multiple conditions.
        """
        if len(history) < 1:
            return 50.0
        
        # Conditions: previous zodiac, big/small, odd/even
        last_entry = history[0]
        last_zodiac = self.normalize_zodiac(last_entry.get('tema_zodiac', ''))
        last_tema = last_entry.get('tema', 25)
        last_big = last_tema > 24  # Big if > 24
        last_odd = last_tema % 2 == 1
        
        # Count occurrences matching all conditions
        matching_count = 0
        total_similar = 0
        
        for i in range(len(history) - 1):
            current = history[i]
            current_zodiac = self.normalize_zodiac(current.get('tema_zodiac', ''))
            current_tema = current.get('tema', 25)
            current_big = current_tema > 24
            current_odd = current_tema % 2 == 1
            
            # If current matches conditions
            if current_zodiac == last_zodiac and current_big == last_big and current_odd == last_odd:
                total_similar += 1
                next_zodiac = self.normalize_zodiac(history[i + 1].get('tema_zodiac', ''))
                if next_zodiac == zodiac:
                    matching_count += 1
        
        if total_similar == 0:
            return 50.0  # Neutral prior
        
        # Posterior probability
        probability = matching_count / total_similar
        return probability * 100
    
    # === Number Properties Dimensions ===
    
    def _score_number_hot_cold(self, history: List[Dict], zodiac: str) -> float:
        """Number hot/cold analysis (5%)
        
        Analyzes temperature of specific numbers in the zodiac.
        """
        tema_list = [h.get('tema', 0) for h in history[:50]]
        zodiac_nums = ZODIAC_NUMBERS[zodiac]
        
        # Count appearances of this zodiac's numbers
        count = sum(1 for t in tema_list if t in zodiac_nums)
        
        # Cold numbers (low frequency) get higher scores
        expected = len(tema_list) * len(zodiac_nums) / 49
        
        if count < expected:
            return min(100.0, ((expected - count) / expected) * 100)
        else:
            return max(0.0, 50.0 - ((count - expected) / expected) * 30)
    
    def _score_tail_trend(self, history: List[Dict], zodiac: str) -> float:
        """Tail trend analysis (5%)
        
        Analyzes the trend of number tails (units digit).
        """
        recent_20 = [h.get('tema', 0) for h in history[:20]]
        
        # Get tail distribution
        tail_counter = Counter([t % 10 for t in recent_20])
        
        # Get tails for this zodiac's numbers
        zodiac_tails = set(num % 10 for num in ZODIAC_NUMBERS[zodiac])
        
        # Score based on cold tails
        total_score = 0
        for tail in zodiac_tails:
            count = tail_counter.get(tail, 0)
            # Less frequent = higher score
            tail_score = max(0, 10 - count * 2)
            total_score += tail_score
        
        return min(100.0, (total_score / len(zodiac_tails)) * 10)
    
    def _score_big_small(self, history: List[Dict], zodiac: str) -> float:
        """Big/Small analysis (5%)
        
        Analyzes big (>24) vs small (<=24) number trends.
        """
        recent_20 = [h.get('tema', 0) for h in history[:20]]
        
        big_count = sum(1 for t in recent_20 if t > 24)
        small_count = 20 - big_count
        
        # Get big/small composition of zodiac numbers
        zodiac_nums = ZODIAC_NUMBERS[zodiac]
        zodiac_big = sum(1 for n in zodiac_nums if n > 24)
        zodiac_small = len(zodiac_nums) - zodiac_big
        
        # Favor the opposite trend (if recent had many big, favor small)
        if big_count > small_count and zodiac_small > zodiac_big:
            return 80.0  # Small zodiac after big trend
        elif small_count > big_count and zodiac_big > zodiac_small:
            return 80.0  # Big zodiac after small trend
        else:
            return 50.0  # Neutral
    
    def _score_odd_even(self, history: List[Dict], zodiac: str) -> float:
        """Odd/Even analysis (5%)
        
        Analyzes odd vs even number trends.
        """
        recent_20 = [h.get('tema', 0) for h in history[:20]]
        
        odd_count = sum(1 for t in recent_20 if t % 2 == 1)
        even_count = 20 - odd_count
        
        # Get odd/even composition of zodiac numbers
        zodiac_nums = ZODIAC_NUMBERS[zodiac]
        zodiac_odd = sum(1 for n in zodiac_nums if n % 2 == 1)
        zodiac_even = len(zodiac_nums) - zodiac_odd
        
        # Favor the opposite trend
        if odd_count > even_count and zodiac_even > zodiac_odd:
            return 80.0  # Even zodiac after odd trend
        elif even_count > odd_count and zodiac_odd > zodiac_even:
            return 80.0  # Odd zodiac after even trend
        else:
            return 50.0  # Neutral
    
    # === Metaphysical Patterns Dimensions ===
    
    def _score_zodiac_relationship(self, history: List[Dict], zodiac: str) -> float:
        """Zodiac relationship analysis (5%)
        
        Analyzes Liu Chong (six clashes), San He (three harmonies), Liu He (six harmonies).
        """
        if len(history) < 1:
            return 50.0
        
        last_zodiac = self.normalize_zodiac(history[0].get('tema_zodiac', ''))
        
        score = 50.0  # Base score
        
        # Liu Chong (六冲) - if last zodiac clashes, penalize
        if ZODIAC_LIU_CHONG.get(last_zodiac) == zodiac:
            score -= 20.0
        
        # San He (三合) - if in harmony trio, bonus
        if zodiac in ZODIAC_SAN_HE.get(last_zodiac, []):
            score += 30.0
        
        # Liu He (六合) - if in harmony pair, bonus
        if ZODIAC_LIU_HE.get(last_zodiac) == zodiac:
            score += 40.0
        
        return max(0.0, min(100.0, score))
    
    def _score_five_elements(self, history: List[Dict], zodiac: str) -> float:
        """Five elements analysis (5%)
        
        Analyzes mutual generation (相生) and restriction (相克) of five elements.
        """
        if len(history) < 1:
            return 50.0
        
        last_zodiac = self.normalize_zodiac(history[0].get('tema_zodiac', ''))
        
        last_element = ZODIAC_FIVE_ELEMENTS.get(last_zodiac, '土')
        current_element = ZODIAC_FIVE_ELEMENTS.get(zodiac, '土')
        
        score = 50.0  # Base score
        
        # Mutual generation (相生) - bonus
        if ELEMENTS_GENERATE.get(last_element) == current_element:
            score += 40.0
        
        # Mutual restriction (相克) - penalty
        if ELEMENTS_RESTRICT.get(last_element) == current_element:
            score -= 30.0
        
        return max(0.0, min(100.0, score))
    
    def _score_color_wave(self, history: List[Dict], zodiac: str) -> float:
        """Color wave analysis (5%)
        
        Analyzes red/blue/green wave trends.
        """
        recent_15 = [h.get('tema', 0) for h in history[:15]]
        
        # Get wave distribution
        wave_counter = Counter([get_color_wave(t) for t in recent_15])
        
        # Get waves for this zodiac's numbers
        zodiac_waves = Counter([get_color_wave(n) for n in ZODIAC_NUMBERS[zodiac]])
        
        # Favor cold waves (least frequent in recent history)
        min_wave = min(wave_counter.values()) if wave_counter else 0
        max_wave = max(wave_counter.values()) if wave_counter else 5
        
        # Calculate score based on zodiac's wave composition
        total_score = 0
        for wave, count in zodiac_waves.items():
            recent_count = wave_counter.get(wave, 0)
            # Less frequent wave = higher score
            wave_score = max(0, (max_wave - recent_count) * 10)
            total_score += wave_score * count
        
        return min(100.0, total_score / sum(zodiac_waves.values()))
    
    # === Validation & Correction Dimensions ===
    
    def _score_monte_carlo(self, history: List[Dict], zodiac: str) -> float:
        """Monte Carlo simulation (5%)
        
        Simulates future draws based on historical probability.
        Uses reduced iteration count (100) for performance vs accuracy trade-off.
        """
        if len(history) < 10:
            return 50.0
        
        # Calculate historical probability for each zodiac
        zodiac_list = [self.normalize_zodiac(h.get('tema_zodiac', '')) for h in history]
        zodiac_counter = Counter(zodiac_list)
        total_count = len(zodiac_list)
        
        # Get probability distribution
        probabilities = {}
        for z in self.all_zodiacs:
            count = zodiac_counter.get(z, 0)
            probabilities[z] = (count + 1) / (total_count + 12)  # Laplace smoothing
        
        # Normalize probabilities
        prob_sum = sum(probabilities.values())
        probabilities = {z: p / prob_sum for z, p in probabilities.items()}
        
        # Monte Carlo simulation
        simulated_count = 0
        
        for _ in range(MONTE_CARLO_ITERATIONS):
            # Weighted random choice
            rand_val = random.random()
            cumulative = 0.0
            for z, prob in probabilities.items():
                cumulative += prob
                if rand_val <= cumulative:
                    if z == zodiac:
                        simulated_count += 1
                    break
        
        # Score based on simulation result
        simulated_probability = simulated_count / MONTE_CARLO_ITERATIONS
        return simulated_probability * 100
    
    def _score_repeat_penalty(self, zodiac: str, recent_predictions: List[str]) -> float:
        """Repeat prediction penalty (3%)
        
        Penalizes zodiacs that were recently predicted.
        """
        if not recent_predictions:
            return 100.0
        
        # Count recent predictions of this zodiac
        count = recent_predictions.count(zodiac)
        
        # Heavy penalty for recent predictions
        if count == 0:
            return 100.0
        elif count == 1:
            return 60.0
        elif count == 2:
            return 30.0
        else:
            return 0.0  # Predicted 3+ times recently
    
    def _score_prime_composite(self, history: List[Dict], zodiac: str) -> float:
        """Prime/Composite analysis (2%)
        
        Analyzes prime vs composite number trends.
        """
        def is_prime(n):
            if n < 2:
                return False
            if n == 2:
                return True
            if n % 2 == 0:
                return False
            for i in range(3, int(n ** 0.5) + 1, 2):
                if n % i == 0:
                    return False
            return True
        
        recent_15 = [h.get('tema', 0) for h in history[:15]]
        
        prime_count = sum(1 for t in recent_15 if is_prime(t))
        composite_count = 15 - prime_count
        
        # Get prime/composite composition of zodiac numbers
        zodiac_nums = ZODIAC_NUMBERS[zodiac]
        zodiac_prime = sum(1 for n in zodiac_nums if is_prime(n))
        zodiac_composite = len(zodiac_nums) - zodiac_prime
        
        # Favor the opposite trend
        if prime_count > composite_count and zodiac_composite > zodiac_prime:
            return 80.0
        elif composite_count > prime_count and zodiac_prime > zodiac_composite:
            return 80.0
        else:
            return 50.0
