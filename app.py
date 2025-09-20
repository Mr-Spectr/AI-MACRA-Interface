import os
os.environ['FLASK_SKIP_DOTENV'] = '1'

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple in-memory cache to reduce API calls
class DataCache:
    def __init__(self, cache_duration_minutes=15):
        self.cache = {}
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.cache_duration:
                logger.info(f"Cache hit for {key}")
                return data
            else:
                # Remove expired cache entry
                del self.cache[key]
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, datetime.now())
        logger.info(f"Cached data for {key}")

# Global cache instance
cache = DataCache()

# Create templates directory if it doesn't exist
os.makedirs('templates', exist_ok=True)

app = Flask(__name__)
CORS(app)

class StockAnalyzer:
    def __init__(self):
        self.news_api_key = 'demo_key'
        # Use environment variable for API key in production
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', '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')
        
        # Mock data for when Yahoo Finance is unavailable
        self.mock_data = {
            'AMZN': {
                'symbol': 'AMZN',
                'name': 'Amazon.com Inc',
                'current_price': 145.86,
                'change': -1.2,
                'volume': 45234567,
                'market_cap': 1523000000000,
                'pe_ratio': 47.3,
                'dividend_yield': 0.0,
                'historical_data': []
            },
            'TSLA': {
                'symbol': 'TSLA',
                'name': 'Tesla Inc',
                'current_price': 248.50,
                'change': 2.8,
                'volume': 78456123,
                'market_cap': 789000000000,
                'pe_ratio': 62.4,
                'dividend_yield': 0.0,
                'historical_data': []
            },
            'AAPL': {
                'symbol': 'AAPL',
                'name': 'Apple Inc',
                'current_price': 221.27,
                'change': 0.8,
                'volume': 34567890,
                'market_cap': 3400000000000,
                'pe_ratio': 33.7,
                'dividend_yield': 0.44,
                'historical_data': []
            },
            'GOOGL': {
                'symbol': 'GOOGL',
                'name': 'Alphabet Inc',
                'current_price': 163.74,
                'change': 1.5,
                'volume': 23456789,
                'market_cap': 2100000000000,
                'pe_ratio': 24.8,
                'dividend_yield': 0.0,
                'historical_data': []
            },
            'MSFT': {
                'symbol': 'MSFT',
                'name': 'Microsoft Corporation',
                'current_price': 416.42,
                'change': 0.6,
                'volume': 19876543,
                'market_cap': 3100000000000,
                'pe_ratio': 35.2,
                'dividend_yield': 0.72,
                'historical_data': []
            }
        }
    
    # ... rest of your existing code stays the same ...
    def get_stock_data(self, symbol):
        """Get stock data with caching and improved error handling"""
        try:
            if not symbol or len(symbol) > 10:
                return {'error': 'Invalid stock symbol'}
            
            # Check cache first
            cache_key = f"stock_data_{symbol.upper()}"
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data
                
            logger.info(f"Fetching fresh data for {symbol}")
            
            # Retry logic with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Add progressive delay to avoid rate limiting
                    delay = 2.0 * (attempt + 1)  # 2, 4, 6 seconds
                    time.sleep(delay)
                    
                    stock = yf.Ticker(symbol)
                    hist = stock.history(period="1y")
                    info = stock.info
                    
                    if not info:
                        if attempt < max_retries - 1:
                            logger.warning(f"No data for {symbol}, retrying attempt {attempt + 2}")
                            continue
                        else:
                            error_msg = f'No data found for symbol {symbol}. Please verify the symbol and try again in a few minutes.'
                            return {'error': error_msg}
                    
                    result = {
                        'symbol': symbol,
                        'name': info.get('longName', info.get('shortName', 'N/A')),
                        'current_price': info.get('currentPrice', hist['Close'][-1] if len(hist) > 0 else 0),
                        'change': info.get('regularMarketChangePercent', 0),
                        'volume': info.get('volume', info.get('regularMarketVolume', 0)),
                        'market_cap': info.get('marketCap', 'N/A'),
                        'pe_ratio': info.get('trailingPE', info.get('forwardPE', 'N/A')),
                        'dividend_yield': info.get('dividendYield', 0),
                        'historical_data': hist.tail(30).to_dict('records') if len(hist) > 0 else []
                    }
                    
                    # Cache the successful result
                    cache.set(cache_key, result)
                    return result
                    
                except Exception as retry_error:
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {symbol}: {str(retry_error)}")
                        continue
                    else:
                        # Last attempt failed, raise the error
                        raise retry_error
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error fetching stock data for {symbol}: {error_msg}")
            
            # Check if we have mock data for this symbol
            symbol_upper = symbol.upper()
            if symbol_upper in self.mock_data:
                print(f"Using demo data for {symbol} due to API unavailability")
                mock_result = self.mock_data[symbol_upper].copy()
                mock_result['demo_mode'] = True
                mock_result['demo_message'] = "📊 Demo Mode: Yahoo Finance API is temporarily unavailable. Showing sample data."
                
                # Cache the mock data briefly
                cache_key = f"stock_data_{symbol.upper()}"
                cache.set(cache_key, mock_result)
                return mock_result
            
            # Handle specific error types for unsupported symbols
            if "429" in error_msg or "Too Many Requests" in error_msg:
                return {'error': f'Rate limit reached for {symbol}. Try waiting 10-15 minutes, or use supported demo symbols: AAPL, AMZN, GOOGL, TSLA, MSFT.'}
            elif "404" in error_msg or "not found" in error_msg.lower():
                return {'error': f'Stock symbol {symbol} not found. Try supported symbols: AAPL, AMZN, GOOGL, TSLA, MSFT.'}
            else:
                return {'error': f'Unable to fetch data for {symbol}. API temporarily unavailable. Try: AAPL, AMZN, GOOGL, TSLA, MSFT.'}
    
    def get_mock_data_if_available(self, symbol):
        """Get mock data for supported symbols"""
        return self.mock_data.get(symbol.upper())
    
    def analyze_stock(self, symbol):
        stock_data = self.get_stock_data(symbol)
        if 'error' in stock_data:
            return stock_data
            
        # Enhanced AI-like analysis
        price = stock_data.get('current_price', 0)
        change = float(stock_data.get('change', 0)) if stock_data.get('change') is not None else 0
        volume = int(stock_data.get('volume', 0)) if stock_data.get('volume') is not None else 0
        pe_ratio = stock_data.get('pe_ratio', 'N/A')
        
        # Multi-factor scoring system
        score = 50  # Base score
        factors = []
        
        # Price momentum analysis
        if change > 5:
            score += 25
            sentiment = "🚀 Strong Buy"
            analysis = "Excellent momentum! Stock showing strong upward trend with great buying opportunity."
            factors.append("Strong positive momentum (+5%)")
        elif change > 0:
            score += 15
            sentiment = "📈 Buy"
            analysis = "Positive trend detected. Good entry point for investors."
            factors.append("Positive price movement")
        elif change > -5:
            score += 5
            sentiment = "⚖️ Hold"
            analysis = "Neutral market conditions. Monitor for trend changes."
            factors.append("Stable price action")
        else:
            score -= 15
            sentiment = "📉 Sell"
            analysis = "Downward trend detected. Consider risk management strategies."
            factors.append("Negative price momentum")
        
        # Volume analysis
        if volume > 1000000:
            score += 10
            factors.append("High trading volume (strong interest)")
        elif volume > 100000:
            score += 5
            factors.append("Moderate trading activity")
        
        # Valuation analysis
        if isinstance(pe_ratio, (int, float)) and pe_ratio > 0:
            if pe_ratio < 15:
                score += 10
                factors.append("Attractive valuation (low P/E)")
            elif pe_ratio < 25:
                score += 5
                factors.append("Fair valuation")
            else:
                score -= 5
                factors.append("High valuation (expensive)")
        
        # Risk assessment
        risk_level = 'Low' if score >= 70 else 'Medium' if score >= 50 else 'High'
        
        return {
            'symbol': symbol,
            'sentiment': sentiment,
            'analysis': analysis,
            'factors': factors,
            'score': max(0, min(100, score)),
            'recommendation': f"Based on comprehensive analysis: {sentiment.split(' ')[1].lower()} recommendation.",
            'confidence': min(95, int(abs(change) * 8 + 65)),
            'risk_level': risk_level
        }
    
    def get_news(self, symbol):
        """Get news data with caching"""
        # Check cache first
        cache_key = f"news_data_{symbol.upper()}"
        cached_news = cache.get(cache_key)
        if cached_news:
            return cached_news
        
        # Fallback news since we removed the API dependency
        news_data = [
            {
                'title': f'{symbol} Market Analysis Update',
                'description': f'Stay updated with the latest {symbol} market trends, financial performance, and investment insights.',
                'url': f'https://finance.yahoo.com/quote/{symbol}/news',
                'publishedAt': datetime.now().isoformat()
            },
            {
                'title': f'{symbol} Stock Performance Review',
                'description': 'Monitor key financial metrics, technical indicators, and market sentiment for informed investment decisions.',
                'url': f'https://finance.yahoo.com/quote/{symbol}',
                'publishedAt': datetime.now().isoformat()
            },
            {
                'title': f'{symbol} Investment Research',
                'description': 'Access professional analysis, earnings reports, and market commentary from financial experts.',
                'url': f'https://finance.yahoo.com/quote/{symbol}/analysis',
                'publishedAt': datetime.now().isoformat()
            }
        ]
        
        # Cache the news data
        cache.set(cache_key, news_data)
        return news_data
    
    def get_ai_response(self, user_message, stock_context=None):
        """Get AI response using OpenRouter API with fallback"""
        try:
            # First, return a smart local response for common queries to avoid API calls
            if self.should_use_fallback(user_message):
                return self.get_fallback_response(user_message, stock_context)
                
            headers = {
                'Authorization': f'Bearer {self.openai_api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://macra-ai-analyzer.com',
                'X-Title': 'MACRA Market Analyzer'
            }
            
            # Create context-aware system message
            system_message = """You are MACRA AI, an expert financial advisor and stock market analyst. You help users understand stock investing, market trends, and financial concepts in simple, beginner-friendly terms. 

Key guidelines:
- Provide clear, educational responses about stocks and investing
- Use emojis to make responses engaging  
- Always remind users that this is not financial advice
- Focus on educational content and risk awareness
- Be encouraging but realistic about investing risks
- Keep responses concise and easy to understand
- If asked about specific stocks, provide educational analysis based on general market principles

You are integrated into the MACRA Market Analyzer platform that provides real-time stock data and AI analysis."""
            
            # Add stock context if provided
            if stock_context:
                system_message += f"\n\nCurrent stock context: {stock_context}"
            
            # Try different model options in case one fails
            models_to_try = [
                "meta-llama/llama-3.1-8b-instruct:free",
                "microsoft/phi-3-mini-128k-instruct:free", 
                "google/gemma-2-9b-it:free"
            ]
            
            for model in models_to_try:
                try:
                    data = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": 400,
                        "temperature": 0.7
                    }
                    
                    response = requests.post(
                        'https://openrouter.ai/api/v1/chat/completions',
                        headers=headers,
                        json=data,
                        timeout=15  # Reduced timeout
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if 'choices' in result and len(result['choices']) > 0:
                            return result['choices'][0]['message']['content']
                    elif response.status_code == 401:
                        # API key issue, use fallback immediately
                        break
                    elif response.status_code == 429:
                        continue  # Try next model if rate limited
                    else:
                        print(f"API Error {response.status_code}: {response.text}")
                        continue
                        
                except requests.exceptions.RequestException as e:
                    print(f"Request error with model {model}: {str(e)}")
                    continue
            
            # If all models fail, return a helpful fallback response
            return self.get_fallback_response(user_message, stock_context)
                
        except Exception as e:
            print(f"AI Response Error: {str(e)}")
            return self.get_fallback_response(user_message, stock_context)
    
    def should_use_fallback(self, user_message):
        """Determine if we should use local fallback instead of API"""
        message_lower = user_message.lower()
        # Use fallback for common/simple questions to reduce API calls
        # Also use fallback for initial empty/minimal messages and stock recommendation questions
        fallback_triggers = [
            'hello', 'hi', 'help', 'what can you do', 'how to start', 'beginner', 'hey',
            'what stock should i buy', 'which stock', 'recommend stock', 'should buy',
            'good stock to buy', 'best stock'
        ]
        return any(trigger in message_lower for trigger in fallback_triggers) or len(message_lower.strip()) < 5
    
    def get_fallback_response(self, user_message, stock_context=None):
        """Provide intelligent fallback responses when AI API is unavailable"""
        message_lower = user_message.lower().strip()
        
        # Handle greetings and initial chat (including empty or minimal messages)
        if not message_lower or any(word in message_lower for word in ['hello', 'hi', 'hey', 'start']):
            return """🤖 Hi! I'm your MACRA AI assistant, here to help you learn about stocks and investing! 

💡 **I can help you with:**
• Understanding stock analysis and metrics
• Explaining investment concepts for beginners
• Risk assessment and management strategies
• Market trends and economic indicators

📈 **Popular Questions:**
• "How do I start investing?"
• "What does P/E ratio mean?"
• "Is [STOCK] a good buy?"
• "How risky is this investment?"

What would you like to learn about?"""

        # Stock recommendation questions
        elif any(word in message_lower for word in ['buy', 'sell', 'invest', 'good stock', 'should buy', 'recommend', 'which stock']):
            return """� **Stock Investment Guidance:**

I can't recommend specific stocks to buy, but I can teach you how to choose wisely! 

🔍 **Research Process:**
• **Step 1**: Use our analyzer above to check AMZN, AAPL, TSLA, GOOGL, or MSFT
• **Step 2**: Look for companies with strong financials and reasonable P/E ratios
• **Step 3**: Consider your risk tolerance and investment timeline
• **Step 4**: Diversify - don't put all money in one stock!

📊 **Key Metrics to Check:**
• P/E Ratio (15-25 is often reasonable)
• Revenue growth over time
• Market cap and trading volume
• Industry position and competition

⚠️ **Important**: This is educational guidance, not financial advice. Start with small amounts, learn as you go, and consider consulting a financial advisor!

Try analyzing a stock above to see these principles in action! 📈"""

        # P/E ratio questions
        elif 'p/e' in message_lower or 'pe ratio' in message_lower or 'price to earnings' in message_lower:
            return """📊 **P/E Ratio Explained Simply:**

The Price-to-Earnings ratio compares a stock's price to its annual earnings per share.

• **Low P/E (under 15)**: Potentially undervalued, but verify why
• **Medium P/E (15-25)**: Generally fair valuation  
• **High P/E (over 25)**: May be overvalued or high-growth company

💡 **Example**: If a stock costs $100 and earns $5 per share annually, P/E = 20

⚠️ **Tip**: Compare P/E ratios within the same industry for better context!"""

        # Risk questions
        elif any(word in message_lower for word in ['risk', 'safe', 'dangerous']):
            return """🛡️ **Stock Investment Risks:**

• **Market Risk**: Prices fluctuate with overall market conditions
• **Company Risk**: Business-specific challenges or failures
• **Sector Risk**: Industry-wide problems (tech crash, oil prices)
• **Inflation Risk**: Purchasing power erosion over time

🎯 **Risk Management Tips**:
• Diversify across different stocks and sectors
• Only invest money you can afford to lose
• Start small and learn gradually
• Consider your time horizon

📊 Our AI analysis includes risk assessment for each stock!"""

        # Beginner questions
        elif any(word in message_lower for word in ['beginner', 'start', 'how to', 'new']):
            return """🌟 **Getting Started with Stock Investing:**

**Step 1**: Learn the basics (you're doing great! 📚)
**Step 2**: Open a brokerage account with reputable firms
**Step 3**: Start with index funds or blue-chip stocks
**Step 4**: Invest regularly, not just once

💡 **Beginner-Friendly Stocks**: Look for established companies like:
• Apple (AAPL) • Microsoft (MSFT) • Google (GOOGL)

⚠️ **Golden Rule**: Never invest more than you can afford to lose!

🚀 Try analyzing these stocks with our tool above!"""

        # Market trend questions  
        elif any(word in message_lower for word in ['market', 'trend', 'economy']):
            return """📈 **Understanding Market Trends:**

• **Bull Market**: Prices rising, investor confidence high 🐂
• **Bear Market**: Prices falling 20%+ from highs 🐻  
• **Correction**: 10-20% decline, often healthy

🔍 **Key Indicators to Watch**:
• Economic data (GDP, employment, inflation)
• Company earnings reports
• Federal Reserve policy changes
• Global events and sentiment

💡 **Pro Tip**: Focus on long-term investing rather than trying to time the market!"""

        # Default response with stock context
        elif stock_context:
            return f"""🤖 I'm here to help with stock and investing questions! 

📊 **Current Analysis Context**: {stock_context}

💭 **Ask me about:**
• How to interpret the analysis results
• What the risk level means
• Investment strategies for beginners
• How to use P/E ratios and other metrics

🚀 What specific aspect of investing would you like to learn about?"""

        # General fallback
        else:
            return """🤖 Hi! I'm your MACRA AI assistant, here to help you learn about stocks and investing! 

💡 **I can help you with:**
• Understanding stock analysis and metrics
• Explaining investment concepts for beginners  
• Risk assessment and management strategies
• Market trends and economic indicators

📈 **Popular Questions:**
• "How do I start investing?"
• "What does P/E ratio mean?"
• "Is [STOCK] a good buy?"
• "How risky is this investment?"

What would you like to learn about? 🚀"""

analyzer = StockAnalyzer()

@app.route('/')
def home():
    """Serve the main application page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error serving home page: {str(e)}")
        # Fallback to serve index.html directly if templates folder issues
        try:
            with open('index.html', 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return "Application temporarily unavailable. Please try again later.", 500

@app.route('/api/stock/<symbol>')
def get_stock(symbol):
    """Get stock data with validation"""
    if not symbol or not symbol.strip():
        return jsonify({'error': 'Stock symbol is required'})
    
    # Clean and validate symbol
    symbol = symbol.strip().upper()[:10]  # Limit length and uppercase
    if not symbol.replace('.', '').replace('-', '').isalnum():
        return jsonify({'error': 'Invalid stock symbol format'})
    
    return jsonify(analyzer.get_stock_data(symbol))

@app.route('/api/analyze/<symbol>')
def analyze(symbol):
    """Analyze stock with validation"""
    if not symbol or not symbol.strip():
        return jsonify({'error': 'Stock symbol is required'})
    
    symbol = symbol.strip().upper()[:10]
    if not symbol.replace('.', '').replace('-', '').isalnum():
        return jsonify({'error': 'Invalid stock symbol format'})
    
    return jsonify(analyzer.analyze_stock(symbol))

@app.route('/api/news/<symbol>')
def news(symbol):
    """Get news with validation"""
    if not symbol or not symbol.strip():
        return jsonify({'error': 'Stock symbol is required'})
    
    symbol = symbol.strip().upper()[:10]
    return jsonify(analyzer.get_news(symbol))

@app.route('/api/chat', methods=['POST'])
def chat_with_ai():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        stock_context = data.get('stock_context', None)
        
        if not user_message.strip():
            return jsonify({'error': 'Please provide a message'})
        
        ai_response = analyzer.get_ai_response(user_message, stock_context)
        
        return jsonify({
            'response': ai_response,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': f'Chat service temporarily unavailable: {str(e)}'})

@app.route('/api/portfolio', methods=['POST'])
def analyze_portfolio():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'})
            
        symbols = data.get('symbols', [])
        if not symbols:
            return jsonify({'error': 'No symbols provided'})
            
        portfolio_analysis = []
        total_score = 0
        
        for symbol in symbols:
            analysis = analyzer.analyze_stock(symbol.upper())
            if 'error' not in analysis:
                portfolio_analysis.append(analysis)
                score = analysis.get('score', 50)
                if isinstance(score, (int, float)):
                    total_score += score
        
        avg_score = total_score / len(portfolio_analysis) if portfolio_analysis else 50
        
        return jsonify({
            'individual_analysis': portfolio_analysis,
            'portfolio_score': round(avg_score, 2),
            'portfolio_sentiment': '🚀 Strong Portfolio' if avg_score >= 70 else '📈 Good Portfolio' if avg_score >= 50 else '⚖️ Balanced Portfolio',
            'total_stocks': len(portfolio_analysis)
        })
    except Exception as e:
        return jsonify({'error': f'Portfolio analysis failed: {str(e)}'})

@app.route('/api/trending')
def trending_stocks():
    trending = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA']
    trending_data = []
    
    for symbol in trending:
        try:
            data = analyzer.get_stock_data(symbol)
            if 'error' not in data:
                trending_data.append(data)
        except:
            continue
    
    return jsonify(trending_data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, load_dotenv=False)