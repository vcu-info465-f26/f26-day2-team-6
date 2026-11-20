
**Currency Conversion Rates Dashboard**
**INFO 465 | Team 6**

**Data Source:** Frankfurter API

**Live Dashboard:** [Currency Conversion Rates Dashboard](https://team6-currency.streamlit.app/)

## Project Overview

The Currency Conversion Rates Dashboard is an interactive web application that allows users to review, compare, and analyze international currency exchange rates. The application provides automated daily data updates, AI-generated summaries, interactive visualizations, and a chatbot that allows users to query currency exchange rate information.


## Why This Project Is Useful

The dashboard provides international investors and individuals interested in global currency markets with an accessible platform for monitoring exchange rates and identifying currency trends.

Users can:

- Review international currency exchange rates.
- Compare currencies and historical exchange rate trends.
- Access AI-generated summaries of exchange rate data.
- Ask questions through an interactive chatbot.
- Monitor daily changes in currency values.
- Make more informed financial decisions using historical data.

## User Story

As an international investor, I want a brief, informative summary of current international exchange rate data and the ability to query data through a chatbot so that I can stay informed about global currency values that interest me.

## Sprint 4 Story Goal

By November 19, users will no longer see cryptocurrencies mixed with traditional currencies on the dashboard, cryptocurrencies will have a dedicated tab, Bitcoin and other supported cryptocurrencies will be compared separately, traditional currencies will remain in the main charts and rankings and country flags will appear alongside traditional currencies to help users identify their associated countries or regions.

## Project Achievements

The development team has successfully implemented the following functionality:

- Retrieves actual currency data from two Frankfurter API endpoints.
- Creates and stores dated currency exchange rate snapshots.
- Loads currency information into a centralized database.
- Generates factual summaries using collected exchange rate data.
- Provides data-driven responses through an interactive chatbot.
- Automatically refreshes exchange rate data daily.
- Displays currency information through an interactive Streamlit dashboard.

## Getting Started

### Access the Live Dashboard

Users can access the application directly without installing any software:

[Launch the Currency Conversion Rates Dashboard](https://team6-currency.streamlit.app/)

### Run the Application Locally

From the root directory of the repository, install the required dependencies:

```bash
pip install -r requirements.txt
```

Launch the Streamlit application:

```bash
python -m streamlit run src/app.py
```

## Help and Support

When submitting an issue, please include:

- A description of the issue.
- Steps to reproduce the issue.
- Expected and actual results.
- Screenshots or error messages, if applicable.

Users may also contact a member of the development team for additional assistance

| Amare | Priceas2@vcu.edu |
| Hassan | Elshowayah@vcu.edu | 
| Alana | maceachronas@vcu.edu |
| Shanika | Rhodessc@vcu.edu |

## Maintainers and Contributors

This project is developed and maintained by INFO 465 Team 6.

| Team Member | Role |

| Hassan | Reviewer |
| Alana | Reviewer |
| Shanika | Project Manager |
| Amare | Tester |

## Data Source

Currency exchange rate information is retrieved through the Frankfurter API.

[Frankfurter API Documentation](https://frankfurter.dev/)

Exchange rate data is refreshed daily and should not be interpreted as live, real-time financial market pricing.
