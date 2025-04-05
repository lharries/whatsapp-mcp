
import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer
from collections import Counter
import numpy as np
import time
import re

# Download required NLTK data
try:
    nltk.data.find('vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon')

st.set_page_config(page_title="WhatsApp Analytics", page_icon="📱", layout="wide")

# Hide Streamlit's default elements
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Add auto-refresh using Streamlit's native rerun
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

# Check if 20 seconds have passed and update silently
current_time = time.time()
if current_time - st.session_state.last_refresh > 20:
    st.session_state.last_refresh = current_time
    # Clear the cache to force data reload
    st.cache_data.clear()
    # Rerun without the page jumping to top
    st.rerun()

DB_PATH = "/Users/govind/Projects/whatsapp-mcp/whatsapp-bridge/store/messages.db"

@st.cache_data(ttl=20)  # Cache expires after 20 seconds
def load_data():
    conn = sqlite3.connect(DB_PATH)
    # Join messages with chats to get contact names
    query = """
    SELECT m.timestamp, m.sender,
           COALESCE(c.name, m.sender) as display_name,
           m.content
    FROM messages m
    LEFT JOIN chats c ON m.chat_jid = c.jid
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Convert to numeric and filter out massive or missing values
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df = df.dropna(subset=['timestamp'])
    
    # Extract time-based features
    df['date'] = df['timestamp'].dt.date
    df['hour'] = df['timestamp'].dt.hour
    df['day_name'] = df['timestamp'].dt.day_name()
    df['month'] = df['timestamp'].dt.month
    df['year'] = df['timestamp'].dt.year
    
    # Calculate message lengths
    df['message_length'] = df['content'].str.len()
    
    # Calculate sentiment
    sia = SentimentIntensityAnalyzer()
    df['sentiment'] = df['content'].apply(lambda x: sia.polarity_scores(str(x))['compound'] if pd.notnull(x) else 0)
    
    return df

def generate_wordcloud(text):
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    return wordcloud

def plot_time_series(df, title):
    fig = px.line(df, x='date', y='count', title=title)
    fig.update_layout(showlegend=True, height=400,
                      xaxis_title='Date',
                      yaxis_title='Number of Messages')
    return fig

def plot_bar(data, x, y, title, orientation='v'):
    fig = px.bar(data, x=x, y=y, title=title)
    fig.update_layout(height=400,
                      xaxis_title=x.replace('_', ' ').title(),
                      yaxis_title='Number of Messages')
    return fig

# Load data
df = load_data()

if df.empty:
    st.error("No valid messages found in the database.")
    st.stop()

# Sidebar configuration and filters
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/6/6b/WhatsApp.svg", width=50)
st.sidebar.title("Filters")

# Reset filters button
if st.sidebar.button("🔄 Reset All Filters"):
    st.session_state.clear()
    st.rerun()

# Time range filters
st.sidebar.subheader("📅 Time Range")
col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input("From", df['date'].min())
with col2:
    end_date = st.date_input("To", df['date'].max())

# Contact filters
st.sidebar.subheader("👥 Contacts")
selected_user = st.sidebar.selectbox("Select contact", ["All"] + sorted(df['display_name'].unique()))

# Message filters
st.sidebar.subheader("💬 Message Filters")

# Message length range
col1, col2 = st.sidebar.columns(2)
with col1:
    min_length = st.number_input("Min length", 0, 1000, 0)
with col2:
    max_length = st.number_input("Max length", min_length, 1000, 1000)

# Content filters
keyword_filter = st.sidebar.text_input("🔍 Search in messages", "", help="Filter messages containing specific words")

# Message type
message_types = st.sidebar.multiselect(
    "Message Type",
    ["Text", "Media", "Links", "Emojis"],
    default=["Text", "Media", "Links", "Emojis"],
    help="Filter by type of message content"
)

# Sentiment analysis
st.sidebar.subheader("😊 Sentiment")
col1, col2 = st.sidebar.columns(2)
with col1:
    sentiment_options = st.multiselect(
        "Emotion",
        ["Positive", "Neutral", "Negative"],
        default=["Positive", "Neutral", "Negative"]
    )
with col2:
    min_sentiment = st.slider(
        "Min Sentiment",
        min_value=-1.0,
        max_value=1.0,
        value=-1.0,
        step=0.1,
        help="Filter messages by minimum sentiment score"
    )

# Time filters
st.sidebar.subheader("⏰ Time Filters")

# Day/Night mode
day_night = st.sidebar.multiselect(
    "Day/Night",
    ["Day (6-18)", "Night (18-6)"],
    default=["Day (6-18)", "Night (18-6)"],
    help="Quick filter for day/night messages"
)

# Detailed time ranges
time_ranges = st.sidebar.multiselect(
    "Specific Hours",
    ["Early Morning (4-8)", "Morning (8-12)", "Afternoon (12-16)", 
     "Evening (16-20)", "Night (20-24)", "Late Night (0-4)"],
    default=["Morning (8-12)", "Afternoon (12-16)", "Evening (16-20)"],
    help="Filter messages by specific time ranges"
)

# Helper functions for message type detection
def has_emoji(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    return bool(emoji_pattern.search(str(text)))

def has_link(text):
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    return bool(url_pattern.search(str(text)))

def has_media(text):
    media_patterns = ["<Media omitted>", "image omitted", "video omitted", "document omitted"]
    return any(pattern.lower() in str(text).lower() for pattern in media_patterns)

# Apply filters with error handling
try:
    filtered_df = df.copy()
    original_df = df.copy()
    filter_warnings = []
    
    # Date filter
    try:
        date_filtered = filtered_df[
            (filtered_df['date'] >= start_date) &
            (filtered_df['date'] <= end_date)
        ]
        if not date_filtered.empty:
            filtered_df = date_filtered
        else:
            filter_warnings.append("No messages in selected date range")
    except Exception as e:
        st.error(f"Error in date filter: {str(e)}")
        filtered_df = original_df
    
    # Contact filter
    if selected_user != "All":
        try:
            contact_filtered = filtered_df[filtered_df['display_name'] == selected_user]
            if not contact_filtered.empty:
                filtered_df = contact_filtered
            else:
                filter_warnings.append(f"No messages from {selected_user}")
                filtered_df = original_df
        except Exception as e:
            st.error(f"Error in contact filter: {str(e)}")
            filtered_df = original_df
    
    # Message length filter
    try:
        length_filtered = filtered_df[
            (filtered_df['message_length'] >= min_length) &
            (filtered_df['message_length'] <= max_length)
        ]
        if not length_filtered.empty:
            filtered_df = length_filtered
        else:
            filter_warnings.append(f"No messages with length between {min_length} and {max_length}")
            filtered_df = original_df
    except Exception as e:
        st.error(f"Error in message length filter: {str(e)}")
        filtered_df = original_df
        
    # Keyword filter
    if keyword_filter:
        try:
            keyword_filtered = filtered_df[filtered_df['content'].str.contains(keyword_filter, case=False, na=False)]
            if not keyword_filtered.empty:
                filtered_df = keyword_filtered
            else:
                filter_warnings.append(f'No messages containing "{keyword_filter}"')
                filtered_df = original_df
        except Exception as e:
            st.error(f"Error in keyword filter: {str(e)}")
            filtered_df = original_df
    
    # Message type filter
    if message_types:
        try:
            type_mask = pd.Series(False, index=filtered_df.index)
            for msg_type in message_types:
                if msg_type == "Text":
                    type_mask |= ~(filtered_df['content'].apply(has_media) | 
                                 filtered_df['content'].apply(has_link) | 
                                 filtered_df['content'].apply(has_emoji))
                elif msg_type == "Media":
                    type_mask |= filtered_df['content'].apply(has_media)
                elif msg_type == "Links":
                    type_mask |= filtered_df['content'].apply(has_link)
                elif msg_type == "Emojis":
                    type_mask |= filtered_df['content'].apply(has_emoji)
            
            type_filtered = filtered_df[type_mask]
            if not type_filtered.empty:
                filtered_df = type_filtered
            else:
                filter_warnings.append("No messages of selected types")
                filtered_df = original_df
        except Exception as e:
            st.error(f"Error in message type filter: {str(e)}")
            filtered_df = original_df
    
    # Sentiment filters
    try:
        # Emotion categories
        sentiment_map = {
            "Positive": (0.05, 1.0),
            "Neutral": (-0.05, 0.05),
            "Negative": (-1.0, -0.05)
        }
        
        # Apply both emotion categories and minimum sentiment
        sentiment_mask = pd.Series(False, index=filtered_df.index)
        
        # Category filter
        if sentiment_options:
            for sentiment in sentiment_options:
                low, high = sentiment_map[sentiment]
                sentiment_mask |= (filtered_df['sentiment'] >= low) & (filtered_df['sentiment'] <= high)
        
        # Minimum sentiment score filter
        sentiment_mask &= (filtered_df['sentiment'] >= min_sentiment)
        
        sentiment_filtered = filtered_df[sentiment_mask]
        if not sentiment_filtered.empty:
            filtered_df = sentiment_filtered
        else:
            filter_warnings.append("No messages matching sentiment criteria")
            filtered_df = original_df
    except Exception as e:
        st.error(f"Error in sentiment filter: {str(e)}")
        filtered_df = original_df
    
    # Time filters
    try:
        time_mask = pd.Series(True, index=filtered_df.index)
        
        # Day/Night filter
        day_night_map = {
            "Day (6-18)": (6, 18),
            "Night (18-6)": (18, 6)
        }
        
        if day_night:
            day_night_mask = pd.Series(False, index=filtered_df.index)
            for period in day_night:
                start_hour, end_hour = day_night_map[period]
                if start_hour < end_hour:
                    day_night_mask |= (filtered_df['hour'] >= start_hour) & (filtered_df['hour'] < end_hour)
                else:  # Handle night that crosses midnight
                    day_night_mask |= (filtered_df['hour'] >= start_hour) | (filtered_df['hour'] < end_hour)
            time_mask &= day_night_mask
        
        # Specific time ranges
        time_range_map = {
            "Early Morning (4-8)": (4, 8),
            "Morning (8-12)": (8, 12),
            "Afternoon (12-16)": (12, 16),
            "Evening (16-20)": (16, 20),
            "Night (20-24)": (20, 0),
            "Late Night (0-4)": (0, 4)
        }
        
        if time_ranges:
            time_range_mask = pd.Series(False, index=filtered_df.index)
            for time_range in time_ranges:
                start_hour, end_hour = time_range_map[time_range]
                if start_hour < end_hour:
                    time_range_mask |= (filtered_df['hour'] >= start_hour) & (filtered_df['hour'] < end_hour)
                else:  # Handle ranges that cross midnight
                    time_range_mask |= (filtered_df['hour'] >= start_hour) | (filtered_df['hour'] < end_hour)
            time_mask &= time_range_mask
        
        time_filtered = filtered_df[time_mask]
        if not time_filtered.empty:
            filtered_df = time_filtered
        else:
            filter_warnings.append("No messages in selected time ranges")
            filtered_df = original_df
    except Exception as e:
        st.error(f"Error in time filter: {str(e)}")
        filtered_df = original_df
    
    # Show filter warnings in a single message
    if filter_warnings:
        st.warning("\n".join(filter_warnings))
        
except Exception as e:
    st.error(f"Error applying filters: {str(e)}")
    filtered_df = original_df

# Main content
st.title("📱 WhatsApp Analytics Dashboard")

# Create tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Overview",
    "👥 Contact Analysis", 
    "📊 Message Analysis",
    "📅 Time Analysis",
    "🔍 Message Explorer"
])

with tab1:
    st.subheader("📊 Key Metrics")
    
    # Key Metrics in columns with colorful cards
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.markdown("""
        <div style='background-color: #e3f2fd; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #1976d2;'>Total Messages</h3>
            <h2 style='margin:0; color: #1976d2;'>{:,}</h2>
        </div>
        """.format(len(filtered_df)), unsafe_allow_html=True)
    
    with col2:
        my_number = ''
        sent_messages = filtered_df[filtered_df['sender'] == my_number].shape[0]
        
        # Update sender display names
        filtered_df.loc[filtered_df['sender'] == my_number, 'display_name'] = 'You'
        st.markdown("""
        <div style='background-color: #e8eaf6; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #3f51b5;'>Messages Sent</h3>
            <h2 style='margin:0; color: #3f51b5;'>{:,}</h2>
        </div>
        """.format(sent_messages), unsafe_allow_html=True)
    
    with col3:
        received_messages = filtered_df[filtered_df['sender'] != my_number].shape[0]
        st.markdown("""
        <div style='background-color: #fce4ec; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #e91e63;'>Messages Received</h3>
            <h2 style='margin:0; color: #e91e63;'>{:,}</h2>
        </div>
        """.format(received_messages), unsafe_allow_html=True)
    
    with col4:
        st.markdown("""
        <div style='background-color: #f3e5f5; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #7b1fa2;'>Unique Contacts</h3>
            <h2 style='margin:0; color: #7b1fa2;'>{:,}</h2>
        </div>
        """.format(filtered_df['display_name'].nunique()), unsafe_allow_html=True)
    
    with col5:
        avg_length = int(filtered_df['message_length'].mean())
        st.markdown("""
        <div style='background-color: #e8f5e9; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #388e3c;'>Avg Length</h3>
            <h2 style='margin:0; color: #388e3c;'>{} chars</h2>
        </div>
        """.format(avg_length), unsafe_allow_html=True)
        
    with col6:
        avg_sentiment = round(filtered_df['sentiment'].mean(), 2)
        sentiment_color = '#4caf50' if avg_sentiment > 0 else '#f44336' if avg_sentiment < 0 else '#ff9800'
        st.markdown("""
        <div style='background-color: #fff3e0; padding: 20px; border-radius: 10px;'>
            <h3 style='margin:0; color: #e65100;'>Avg Sentiment</h3>
            <h2 style='margin:0; color: #e65100;'>{:+.2f}</h2>
        </div>
        """.format(avg_sentiment), unsafe_allow_html=True)
    

    
    # Time series analysis with rolling average
    st.subheader("📈 Message Trends")
    daily_messages = filtered_df.groupby('date').size().reset_index(name='count')
    daily_messages.set_index('date', inplace=True)
    daily_messages['rolling_avg'] = daily_messages['count'].rolling(window=7).mean()
    daily_messages.reset_index(inplace=True)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_messages['date'],
        y=daily_messages['count'],
        name='Daily Messages',
        line=dict(color='#2196f3', width=1)
    ))
    fig.add_trace(go.Scatter(
        x=daily_messages['date'],
        y=daily_messages['rolling_avg'],
        name='7-day Average',
        line=dict(color='#f44336', width=2)
    ))
    fig.update_layout(
        title='Message Activity Over Time',
        height=400,
        showlegend=True,
        xaxis_title='Date',
        yaxis_title='Number of Messages'
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Activity patterns with improved visualizations
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("⏰ Hourly Activity")
        hourly = filtered_df.groupby('hour').size().reset_index(name='count')
        fig = px.bar(hourly, x='hour', y='count',
                    title='Messages by Hour of Day',
                    color='count',
                    color_continuous_scale='Viridis')
        fig.update_layout(
            height=400,
            xaxis_title='Hour of Day',
            yaxis_title='Number of Messages',
            coloraxis_showscale=False
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("📅 Daily Activity")
        daily = filtered_df.groupby('day_name').size().reset_index(name='count')
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        daily['day_name'] = pd.Categorical(daily['day_name'], categories=days_order, ordered=True)
        daily = daily.sort_values('day_name')
        
        fig = px.bar(daily, x='day_name', y='count',
                    title='Messages by Day of Week',
                    color='count',
                    color_continuous_scale='Viridis')
        fig.update_layout(
            height=400,
            xaxis_title='Day of Week',
            yaxis_title='Number of Messages',
            coloraxis_showscale=False
        )
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("👥 Contact Analysis")
    
    # Contact Overview
    col1, col2 = st.columns(2)
    
    with col1:
        # Top active contacts
        st.subheader("Most Active Contacts")
        top_contacts = filtered_df['display_name'].value_counts().head(10).reset_index()
        top_contacts.columns = ['contact', 'count']
        
        fig = px.bar(top_contacts,
                    x='count', y='contact',
                    orientation='h',
                    title='Top 10 Most Active Contacts',
                    color='count',
                    color_continuous_scale='Viridis')
        fig.update_layout(
            height=400,
            yaxis={'categoryorder': 'total ascending'},
            xaxis_title='Number of Messages',
            yaxis_title='Contact',
            coloraxis_showscale=False
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Contact engagement over time
        st.subheader("Contact Engagement Trends")
        top_5_contacts = filtered_df['display_name'].value_counts().head().index
        contact_trends = filtered_df[filtered_df['display_name'].isin(top_5_contacts)]
        
        fig = px.line(contact_trends.groupby(['date', 'display_name']).size().reset_index(name='count'),
                    x='date', y='count', color='display_name',
                    title='Top 5 Contacts Activity Over Time')
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    
    # Contact Sentiment Analysis
    st.subheader("Contact Sentiment Analysis")
    contact_sentiment = filtered_df.groupby('display_name').agg({
        'sentiment': ['mean', 'std', 'count'],
        'message_length': 'mean'
    }).reset_index()
    contact_sentiment.columns = ['contact', 'sentiment_mean', 'sentiment_std', 'message_count', 'avg_length']
    contact_sentiment = contact_sentiment[contact_sentiment['message_count'] > 10].sort_values('sentiment_mean', ascending=False)
    
    if not contact_sentiment.empty:
        fig = px.scatter(contact_sentiment,
                        x='message_count',
                        y='sentiment_mean',
                        size='avg_length',
                        color='sentiment_std',
                        hover_data=['contact', 'message_count', 'avg_length'],
                        text='contact',
                        title='Contact Interaction Analysis',
                        labels={
                            'message_count': 'Number of Messages',
                            'sentiment_mean': 'Average Sentiment',
                            'sentiment_std': 'Sentiment Variability',
                            'avg_length': 'Avg Message Length'
                        })
        fig.update_traces(textposition='top center')
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # Contact interaction patterns
        st.subheader("Contact Interaction Patterns")
        col1, col2 = st.columns(2)
        
        with col1:
            # Message length distribution by contact
            fig = px.box(filtered_df,
                        x='sender',
                        y='message_length',
                        title='Message Length Distribution by Contact',
                        color='sender')
            fig.update_layout(
                height=400,
                xaxis={'tickangle': 45},
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Sentiment distribution by contact
            fig = px.violin(filtered_df,
                        x='sender',
                        y='sentiment',
                        title='Sentiment Distribution by Contact',
                        color='sender')
            fig.update_layout(
                height=400,
                xaxis={'tickangle': 45},
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("📊 Message Content Analysis")
    
    if not filtered_df.empty:
        # Message Statistics
        col1, col2, col3 = st.columns(3)
        with col1:
            avg_words = filtered_df['content'].str.split().str.len().mean()
            st.markdown("""
            <div style='background-color: #e8f5e9; padding: 20px; border-radius: 10px;'>
                <h3 style='margin:0; color: #388e3c;'>Avg Words</h3>
                <h2 style='margin:0;'>{:.1f}</h2>
            </div>
            """.format(avg_words), unsafe_allow_html=True)
        
        with col2:
            positive_pct = (filtered_df['sentiment'] > 0.05).mean() * 100
            st.markdown("""
            <div style='background-color: #f3e5f5; padding: 20px; border-radius: 10px;'>
                <h3 style='margin:0; color: #7b1fa2;'>Positive %</h3>
                <h2 style='margin:0;'>{:.1f}%</h2>
            </div>
            """.format(positive_pct), unsafe_allow_html=True)
        
        with col3:
            negative_pct = (filtered_df['sentiment'] < -0.05).mean() * 100
            st.markdown("""
            <div style='background-color: #ffebee; padding: 20px; border-radius: 10px;'>
                <h3 style='margin:0; color: #c62828;'>Negative %</h3>
                <h2 style='margin:0;'>{:.1f}%</h2>
            </div>
            """.format(negative_pct), unsafe_allow_html=True)
        
        # Word Cloud and Sentiment
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🌐 Word Cloud")
            text = ' '.join(filtered_df['content'].dropna().astype(str))
            wordcloud = generate_wordcloud(text)
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis('off')
            st.pyplot(fig)
        
        with col2:
            st.subheader("😊 Sentiment Analysis")
            sentiment_labels = pd.cut(filtered_df['sentiment'],
                                    bins=[-1, -0.05, 0.05, 1],
                                    labels=['Negative', 'Neutral', 'Positive'])
            sentiment_counts = sentiment_labels.value_counts()
            
            fig = px.pie(values=sentiment_counts.values,
                        names=sentiment_counts.index,
                        title='Message Sentiment Distribution',
                        color=sentiment_counts.index,
                        color_discrete_map={
                            'Positive': '#4caf50',
                            'Neutral': '#ff9800',
                            'Negative': '#f44336'
                        })
            fig.update_traces(textposition='inside', textinfo='percent+label')
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        
        # Message Length Analysis
        st.subheader("📋 Message Length Analysis")
        col1, col2 = st.columns(2)
        
        with col1:
            fig = px.histogram(filtered_df,
                            x='message_length',
                            nbins=50,
                            title='Message Length Distribution',
                            color_discrete_sequence=['#2196f3'])
            fig.update_layout(
                height=400,
                xaxis_title='Message Length (characters)',
                yaxis_title='Number of Messages'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.scatter(filtered_df,
                            x='message_length',
                            y='sentiment',
                            title='Message Length vs Sentiment',
                            color='sentiment',
                            color_continuous_scale='RdYlGn')
            fig.update_layout(
                height=400,
                xaxis_title='Message Length (characters)',
                yaxis_title='Sentiment Score'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Common Words Analysis
        st.subheader("📖 Common Words Analysis")
        words = ' '.join(filtered_df['content'].dropna().astype(str)).lower().split()
        word_freq = pd.Series(words).value_counts().head(20)
        
        fig = px.bar(x=word_freq.values,
                    y=word_freq.index,
                    orientation='h',
                    title='Top 20 Most Common Words',
                    color=word_freq.values,
                    color_continuous_scale='Viridis')
        fig.update_layout(
            height=500,
            xaxis_title='Frequency',
            yaxis_title='Word',
            yaxis={'categoryorder': 'total ascending'}
        )
        st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.subheader("📅 Time Analysis")
    
    # Monthly Trends
    st.subheader("📈 Monthly Activity")
    monthly_messages = filtered_df.groupby(['year', 'month']).size().reset_index(name='count')
    monthly_messages['date'] = pd.to_datetime(monthly_messages[['year', 'month']].assign(day=1))
    
    fig = px.line(monthly_messages,
                x='date',
                y='count',
                title='Monthly Message Trends',
                markers=True)
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    
    # Weekly Heatmap
    st.subheader("📆 Weekly Activity Patterns")
    filtered_df['weekday'] = filtered_df['timestamp'].dt.day_name()
    filtered_df['hour_str'] = filtered_df['hour'].astype(str).str.zfill(2) + ':00'
    
    weekly_heatmap = filtered_df.groupby(['weekday', 'hour_str']).size().reset_index(name='count')
    weekly_heatmap = weekly_heatmap.pivot(index='weekday', columns='hour_str', values='count')
    
    # Reorder days
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekly_heatmap = weekly_heatmap.reindex(days_order)
    
    fig = px.imshow(weekly_heatmap,
                    title='Message Activity Heatmap',
                    labels=dict(x='Hour of Day', y='Day of Week', color='Messages'),
                    color_continuous_scale='Viridis')
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    
    # Seasonal Analysis
    st.subheader("🌤 Seasonal Patterns")
    col1, col2 = st.columns(2)
    
    with col1:
        # Hour distribution by month
        hourly_monthly = filtered_df.groupby(['month', 'hour']).size().reset_index(name='count')
        fig = px.density_heatmap(hourly_monthly,
                                x='hour',
                                y='month',
                                z='count',
                                title='Message Activity by Month and Hour',
                                labels={'hour': 'Hour of Day', 'month': 'Month'},
                                color_continuous_scale='Viridis')
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Day of week distribution by month
        daily_monthly = filtered_df.groupby(['month', 'day_name']).size().reset_index(name='count')
        daily_monthly['day_name'] = pd.Categorical(daily_monthly['day_name'],
                                                categories=days_order,
                                                ordered=True)
        fig = px.density_heatmap(daily_monthly,
                                x='day_name',
                                y='month',
                                z='count',
                                title='Message Activity by Month and Day',
                                color_continuous_scale='Viridis')
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

with tab5:
    st.subheader("🔍 Message Explorer")
    
    # Search and Filter Options
    col1, col2 = st.columns(2)
    with col1:
        search_query = st.text_input("🔍 Search in messages", "")
    with col2:
        sentiment_filter = st.select_slider(
            "Filter by sentiment",
            options=["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"],
            value=("Very Negative", "Very Positive")
        )
    
    # Apply filters
    explorer_df = filtered_df.copy()
    
    # Text search
    if search_query:
        explorer_df = explorer_df[explorer_df['content'].str.contains(search_query, case=False, na=False)]
    
    # Sentiment filter mapping
    sentiment_ranges = {
        "Very Negative": -1.0,
        "Negative": -0.5,
        "Neutral": 0,
        "Positive": 0.5,
        "Very Positive": 1.0
    }
    
    # Apply sentiment filter
    sentiment_min = sentiment_ranges[sentiment_filter[0]]
    sentiment_max = sentiment_ranges[sentiment_filter[1]]
    explorer_df = explorer_df[
        (explorer_df['sentiment'] >= sentiment_min) &
        (explorer_df['sentiment'] <= sentiment_max)
    ]
    
    # Display message statistics
    st.markdown(f"Found **{len(explorer_df)}** messages matching your criteria")
    
    # Display messages with enhanced formatting
    if not explorer_df.empty:
        st.dataframe(
            explorer_df[['timestamp', 'display_name', 'content', 'sentiment', 'message_length']]
            .sort_values('timestamp', ascending=False)
            .head(20)
            .style
            .background_gradient(subset=['sentiment'], cmap='RdYlGn')
            .background_gradient(subset=['message_length'], cmap='Blues')
            .format({
                'timestamp': lambda x: x.strftime('%Y-%m-%d %H:%M'),
                'sentiment': '{:.2f}',
                'message_length': '{:,}'
            })
        )
        
        # Message Context View
        if st.checkbox("Show Message Context Analysis"):
            st.subheader("📔 Message Context Analysis")
            
            # Get sample messages for each sentiment category
            sentiment_samples = {
                'Most Positive': explorer_df.nlargest(3, 'sentiment'),
                'Most Negative': explorer_df.nsmallest(3, 'sentiment'),
                'Longest': explorer_df.nlargest(3, 'message_length'),
                'Most Recent': explorer_df.nlargest(3, 'timestamp')
            }
            
            for category, messages in sentiment_samples.items():
                st.write(f"**{category} Messages:**")
                for _, msg in messages.iterrows():
                    st.markdown(f"""
                    <div style='background-color: #f5f5f5; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                        <small>{msg['timestamp'].strftime('%Y-%m-%d %H:%M')} - {msg['display_name']}</small><br>
                        {msg['content']}<br>
                        <small>Sentiment: {msg['sentiment']:.2f} | Length: {msg['message_length']} chars</small>
                    </div>
                    """, unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown("📱 **WhatsApp Analytics Dashboard** | Created with Streamlit")