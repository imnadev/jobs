import os
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not found in environment variables!")
    exit(1)

# Job management
class Job:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.from_station = None
        self.to_station = None
        self.date_range = None
        self.selected_trains = []
        self.interval = 10
        self.car_types = []
        self.is_running = False
        self.task = None
        self.request_history = []
        
    def add_request_status(self, status: str, data: Any = None):
        self.request_history.append({
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': status,
            'data': data
        })
        # Keep only last 10 requests
        if len(self.request_history) > 10:
            self.request_history = self.request_history[-10:]

# Global job storage
jobs: Dict[int, Job] = {}
user_states: Dict[int, Dict] = {}

# API headers
API_HEADERS = {
    'api_version': '1',
    'device_os': 'WINDOWS',
    'language': 'uz'
}

async def search_stations(query: str) -> List[Dict]:
    """Search for stations by query."""
    url = f"https://tickets.atto.uz/v1.0/customer/railways/stations/list?search={query}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=API_HEADERS) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('success') and data.get('data', {}).get('success'):
                    return data['data']['items']
    return []

async def search_trains(station_from: int, station_to: int, from_name: str, to_name: str, dep_date: str) -> List[Dict]:
    """Search for trains between stations."""
    url = f"https://tickets.atto.uz/v1.0/customer/railways/search/trains"
    params = {
        'stationTo': station_to,
        'stationFrom': station_from,
        'fromName': from_name,
        'toName': to_name,
        'depDate': dep_date,
        '_updTime': str(int(datetime.now().timestamp() * 1000)),
        'transportType': 'train'
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=API_HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('success') and data.get('data', {}).get('success'):
                    return data['data']['items']
    return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! I'm a train ticket monitoring bot. Use /new to create a new monitoring job.",
    )

async def new_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /new command."""
    user_id = update.effective_user.id
    
    # Cancel existing job if any
    if user_id in jobs and jobs[user_id].is_running:
        jobs[user_id].is_running = False
        if jobs[user_id].task:
            jobs[user_id].task.cancel()
    
    # Create new job
    jobs[user_id] = Job(user_id)
    user_states[user_id] = {'step': 'from_station'}
    
    await update.message.reply_text("Creating new monitoring job. Please enter the departure station name:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages based on current state."""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in user_states:
        await update.message.reply_text("Please use /new to create a new job first.")
        return
    
    state = user_states[user_id]
    step = state.get('step')
    
    if step == 'from_station':
        await handle_station_search(update, text, 'from_station')
    elif step == 'to_station':
        await handle_station_search(update, text, 'to_station')
    elif step == 'date_range':
        await handle_date_range(update, text)
    elif step == 'interval':
        await handle_interval(update, text)

async def handle_station_search(update: Update, query: str, station_type: str) -> None:
    """Handle station search and selection."""
    user_id = update.effective_user.id
    
    stations = await search_stations(query)
    
    if not stations:
        await update.message.reply_text("No stations found. Please try another search term.")
        return
    
    # Create inline keyboard
    keyboard = []
    for station in stations:
        keyboard.append([InlineKeyboardButton(
            f"{station['name']} ({station['code']})",
            callback_data=f"select_{station_type}_{station['code']}_{station['name']}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Select {station_type.replace('_', ' ')}:", reply_markup=reply_markup)

async def handle_date_range(update: Update, text: str) -> None:
    """Handle date range input."""
    user_id = update.effective_user.id
    
    try:
        # Validate date range format (DD.MM.YYYY-DD.MM.YYYY)
        if '-' not in text:
            raise ValueError("Invalid format")
        
        start_date, end_date = text.split('-')
        datetime.strptime(start_date.strip(), '%d.%m.%Y')
        datetime.strptime(end_date.strip(), '%d.%m.%Y')
        
        jobs[user_id].date_range = text.strip()
        user_states[user_id]['step'] = 'searching_trains'
        
        await update.message.reply_text("Searching for available trains...")
        await show_train_selection(update, user_id)
        
    except ValueError:
        await update.message.reply_text("Invalid date format. Please use DD.MM.YYYY-DD.MM.YYYY format (e.g., 18.03.2026-19.03.2026)")

async def handle_interval(update: Update, text: str) -> None:
    """Handle interval input."""
    user_id = update.effective_user.id
    
    try:
        interval = int(text.strip())
        if interval < 1:
            raise ValueError("Interval must be at least 1 second")
        
        jobs[user_id].interval = interval
        await update.message.reply_text(f"Interval set to {interval} seconds. Job saved! Use /continue to start monitoring.")
        
        # Clear user state
        del user_states[user_id]
        
    except ValueError:
        await update.message.reply_text("Invalid interval. Please enter a positive number (seconds).")

async def show_train_selection(update: Update, user_id: int) -> None:
    """Show train selection options."""
    job = jobs[user_id]
    from_code = job.from_station['code']
    to_code = job.to_station['code']
    from_name = job.from_station['name']
    to_name = job.to_station['name']
    
    # Use first date from range for search
    start_date = job.date_range.split('-')[0].strip()
    
    trains = await search_trains(from_code, to_code, from_name, to_name, start_date)
    
    if not trains:
        await update.message.reply_text("No trains found for the selected route and date.")
        return
    
    # Store trains for selection
    user_states[user_id]['available_trains'] = trains
    
    # Create inline keyboard
    keyboard = []
    for i, train in enumerate(trains):
        keyboard.append([InlineKeyboardButton(
            f"Train {train['number']} - {train['departure']['time']} → {train['arrival']['time']}",
            callback_data=f"train_{i}"
        )])
    
    keyboard.append([InlineKeyboardButton("Submit Selection", callback_data="submit_trains")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Select trains to monitor:", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith('select_from_station_'):
        await handle_station_selection(query, user_id, 'from_station', data)
    elif data.startswith('select_to_station_'):
        await handle_station_selection(query, user_id, 'to_station', data)
    elif data.startswith('train_'):
        await handle_train_selection(query, user_id, data)
    elif data == 'submit_trains':
        await submit_train_selection(query, user_id)
    elif data.startswith('car_type_'):
        await handle_car_type_selection(query, user_id, data)
    elif data == 'submit_car_types':
        await submit_car_types(query, user_id)

async def handle_station_selection(query, user_id: int, station_type: str, data: str) -> None:
    """Handle station selection."""
    parts = data.split('_')
    code = int(parts[2])
    name = parts[3]
    
    if station_type == 'from_station':
        jobs[user_id].from_station = {'code': code, 'name': name}
        user_states[user_id]['step'] = 'to_station'
        await query.edit_message_text(f"Departure station: {name}. Now enter the destination station:")
    else:
        jobs[user_id].to_station = {'code': code, 'name': name}
        user_states[user_id]['step'] = 'date_range'
        await query.edit_message_text(f"Destination station: {name}. Now enter the date range (DD.MM.YYYY-DD.MM.YYYY):")

async def handle_train_selection(query, user_id: int, data: str) -> None:
    """Handle train selection."""
    train_index = int(data.split('_')[1])
    trains = user_states[user_id]['available_trains']
    selected_train = trains[train_index]
    
    job = jobs[user_id]
    
    # Toggle selection
    train_key = f"{selected_train['number']}_{selected_train['departure']['time']}"
    if train_key in job.selected_trains:
        job.selected_trains.remove(train_key)
    else:
        job.selected_trains.append(train_key)
    
    # Update message
    selected_text = f"Selected trains: {len(job.selected_trains)}"
    await query.edit_message_text(selected_text)

async def submit_train_selection(query, user_id: int) -> None:
    """Submit train selection and move to car type selection."""
    job = jobs[user_id]
    
    if not job.selected_trains:
        await query.edit_message_text("Please select at least one train.")
        return
    
    # Show car type selection
    keyboard = [
        [InlineKeyboardButton("Sleeper", callback_data="car_type_Sleeper")],
        [InlineKeyboardButton("Coupe", callback_data="car_type_Coupe")],
        [InlineKeyboardButton("Others", callback_data="car_type_Others")],
        [InlineKeyboardButton("Submit Selection", callback_data="submit_car_types")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user_states[user_id]['step'] = 'car_types'
    await query.edit_message_text("Select car types to monitor:", reply_markup=reply_markup)

async def handle_car_type_selection(query, user_id: int, data: str) -> None:
    """Handle car type selection."""
    car_type = data.split('_')[2]
    job = jobs[user_id]
    
    # Toggle selection
    if car_type in job.car_types:
        job.car_types.remove(car_type)
    else:
        job.car_types.append(car_type)
    
    selected_text = f"Selected car types: {', '.join(job.car_types) if job.car_types else 'None'}"
    await query.edit_message_text(selected_text)

async def submit_car_types(query, user_id: int) -> None:
    """Submit car type selection and move to interval setting."""
    job = jobs[user_id]
    
    if not job.car_types:
        await query.edit_message_text("Please select at least one car type.")
        return
    
    user_states[user_id]['step'] = 'interval'
    await query.edit_message_text("Enter the monitoring interval in seconds (e.g., 5):")

async def continue_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /continue command."""
    user_id = update.effective_user.id
    
    if user_id not in jobs:
        await update.message.reply_text("No job found. Use /new to create one first.")
        return
    
    job = jobs[user_id]
    
    if job.is_running:
        await update.message.reply_text("Job is already running.")
        return
    
    if not all([job.from_station, job.to_station, job.date_range, job.selected_trains, job.car_types]):
        await update.message.reply_text("Job configuration incomplete. Use /new to create a new job.")
        return
    
    job.is_running = True
    job.task = asyncio.create_task(monitor_trains(update, user_id))
    await update.message.reply_text("Monitoring started!")

async def pause_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /pause command."""
    user_id = update.effective_user.id
    
    if user_id not in jobs or not jobs[user_id].is_running:
        await update.message.reply_text("No running job found.")
        return
    
    jobs[user_id].is_running = False
    if jobs[user_id].task:
        jobs[user_id].task.cancel()
    
    await update.message.reply_text("Job paused.")

async def clear_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command."""
    user_id = update.effective_user.id
    
    if user_id in jobs:
        if jobs[user_id].is_running and jobs[user_id].task:
            jobs[user_id].task.cancel()
        del jobs[user_id]
    
    if user_id in user_states:
        del user_states[user_id]
    
    await update.message.reply_text("Job cleared.")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /interval command."""
    user_id = update.effective_user.id
    
    if user_id not in jobs:
        await update.message.reply_text("No job found. Use /new to create one first.")
        return
    
    if not context.args:
        await update.message.reply_text("Please provide interval in seconds: /interval 5")
        return
    
    try:
        interval = int(context.args[0])
        if interval < 1:
            raise ValueError("Interval must be at least 1 second")
        
        jobs[user_id].interval = interval
        await update.message.reply_text(f"Interval updated to {interval} seconds.")
        
    except ValueError:
        await update.message.reply_text("Invalid interval. Please provide a positive number.")

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command."""
    user_id = update.effective_user.id
    
    if user_id not in jobs:
        await update.message.reply_text("No job found. Use /new to create one first.")
        return
    
    job = jobs[user_id]
    
    status_text = f"Job Status: {'Running' if job.is_running else 'Stopped'}\n"
    status_text += f"Interval: {job.interval} seconds\n"
    status_text += f"From: {job.from_station['name'] if job.from_station else 'Not set'}\n"
    status_text += f"To: {job.to_station['name'] if job.to_station else 'Not set'}\n"
    status_text += f"Date Range: {job.date_range or 'Not set'}\n"
    status_text += f"Selected Trains: {len(job.selected_trains)}\n"
    status_text += f"Car Types: {', '.join(job.car_types) if job.car_types else 'None'}\n\n"
    
    status_text += "Last 10 requests:\n"
    for req in job.request_history[-10:]:
        status_text += f"- {req['timestamp']}: {req['status']}\n"
    
    await update.message.reply_text(status_text)

async def monitor_trains(update: Update, user_id: int) -> None:
    """Monitor trains for available tickets."""
    job = jobs[user_id]
    
    while job.is_running:
        try:
            from_code = job.from_station['code']
            to_code = job.to_station['code']
            from_name = job.from_station['name']
            to_name = job.to_station['name']
            
            # Parse date range and loop through all dates
            start_date_str, end_date_str = job.date_range.split('-')
            start_date = datetime.strptime(start_date_str.strip(), '%d.%m.%Y')
            end_date = datetime.strptime(end_date_str.strip(), '%d.%m.%Y')
            
            current_date = start_date
            total_tickets_found = 0
            
            while current_date <= end_date and job.is_running:
                date_str = current_date.strftime('%d.%m.%Y')
                trains = await search_trains(from_code, to_code, from_name, to_name, date_str)
                
                available_trains = []
                for train in trains:
                    train_key = f"{train['number']}_{train['departure']['time']}"
                    if train_key in job.selected_trains:
                        for car in train.get('cars', []):
                            if car['typeShow'] in job.car_types and int(car['freeSeats']) > 0:
                                available_trains.append({
                                    'train': train,
                                    'car': car,
                                    'date': date_str
                                })
                                break
                
                if available_trains:
                    message = f"🎫 Tickets Available for {date_str}!\n\n"
                    for item in available_trains:
                        train = item['train']
                        car = item['car']
                        message += f"Train {train['number']}: {train['departure']['time']} → {train['arrival']['time']}\n"
                        message += f"{car['typeShow']}: {car['freeSeats']} seats - {car['amount']} UZS\n\n"
                    
                    try:
                        await update.get_bot().send_message(chat_id=user_id, text=message)
                    except:
                        pass  # Handle bot errors gracefully
                    
                    total_tickets_found += len(available_trains)
                
                current_date += datetime.timedelta(days=1)
            
            if total_tickets_found > 0:
                job.add_request_status("Tickets found", total_tickets_found)
            else:
                job.add_request_status("No tickets available")
            
            await asyncio.sleep(job.interval)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in monitor_trains: {e}")
            job.add_request_status(f"Error: {str(e)}")
            await asyncio.sleep(job.interval)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new", new_job))
    application.add_handler(CommandHandler("continue", continue_job))
    application.add_handler(CommandHandler("pause", pause_job))
    application.add_handler(CommandHandler("clear", clear_job))
    application.add_handler(CommandHandler("interval", set_interval))
    application.add_handler(CommandHandler("status", show_status))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    print("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
