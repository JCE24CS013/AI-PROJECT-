# AI Tourist Route Optimizer

A Django-based travel platform for destination planning, route optimization, restaurant discovery, and AI-assisted trip advice.

## Setup

1. Create a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and set your values.
4. Run migrations.
5. Start the development server.

Set `GROQ_API_KEY` in the backend `.env` to use Groq for streamed assistant replies. The default model is `openai/gpt-oss-20b`, with low reasoning effort and a 256-token completion cap for routine travel questions. Groq is preferred; if its key is not configured, the assistant uses the configured OpenRouter key as a setup fallback. Set `AI_PROVIDER=openrouter` to explicitly prefer OpenRouter. Provider failures are shown to the user rather than triggering a second slow request. Check your Groq account limits page for its current model access and free-tier quotas. Keep API keys out of source control and rotate any key shared publicly or in chat.

The route planner can compare bus, car, train, and plane using coordinates stored for destinations in the app, or look up other locations when `GOOGLE_PLACES_API_KEY` is configured. Each itinerary day includes a suggested timed schedule built around catalog destinations. Schedule times and general activity suggestions are not verified venue hours or bookings; check current access, opening times, and local conditions. Distance and travel-time values are indicative estimates, not live directions, road distances, timetables, or fares. The route map uses Esri World Street Map tiles and opens centered on India. After planning a route, use "Open route in Google Maps" for live directions in Google Maps.

Restaurant demo examples and owner-submitted restaurant listings are no longer included in public traveler pages. The previous demo seeding command (`python manage.py seed_demo_restaurants`) has been replaced with a removal command that deletes any existing demo restaurant records. To remove demo restaurants from an existing database, run `python manage.py seed_demo_restaurants` (now a removal command).

To import the user-provided restaurant screenshot entries, run `python manage.py import_restaurant_catalog`. The data is kept in `core/data/restaurant_catalog.csv` and the command can be rerun safely as more entries are added. Imported entries are pending verification; screenshot ratings and review counts are stored separately from app reviews and should be rechecked because public listing data can change. Rows whose addresses were cut off in the screenshots retain only the legible text.

Set `GOOGLE_PLACES_API_KEY` in `.env` and enable Google Places API (New) with billing in Google Cloud to search restaurants. Tourist accounts can use the Search Restaurants page; each search makes one live Places API request. Listing details are displayed directly and are not cached or saved in the database. The separately run ID sync below makes up to five billable requests for one state, or up to five per state/territory with `--all-states`. Results can be fewer than 100 unique places per state; Google does not guarantee a minimum. Follow the [Places API policies](https://developers.google.com/maps/documentation/places/web-service/policies): names, addresses, ratings, and other listing details must not be stored beyond allowed exceptions. Google Places does not provide restaurant menus. Owner-submitted dishes are restaurant-confirmed; regional dish ideas in the chatbot are clearly labeled as suggestions and are not linked to a restaurant's menu.

## Commands

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Sample data

```bash
python manage.py seed_data
```

This command adds a curated selection of tourist places across Indian states and union territories using approximate map coordinates. It is safe to run more than once and preserves existing destination records.

To store Place IDs only for live Google lookup, run one state at a time:

```bash
python manage.py sync_place_ids --state Kerala
```

The all-state option can make up to 180 billable Places API requests. Review Google Cloud billing before running it:

```bash
python manage.py sync_place_ids --all-states
```
