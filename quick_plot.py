import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import glob
import os


def plot_latest_run():
    # 1. Find the latest log
    list_of_files = glob.glob('./*.log')
    if not list_of_files:
        print("No log files found.")
        return

    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"Plotting: {latest_file}")

    with open(latest_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 2. Extract and clean data
    if "Activities log:" not in content:
        print("No Activities log found.")
        return

    raw_activities = content.split("Activities log:")[-1].strip()
    activities_text = raw_activities.split("\n\n")[0].strip()

    df = pd.read_csv(io.StringIO(activities_text), sep=";",
                     on_bad_lines='skip', engine='python')
    df.columns = df.columns.str.strip()
    df = df[df['product'] != 'product']
    df['profit_and_loss'] = pd.to_numeric(
        df['profit_and_loss'], errors='coerce')

    # 3. Create a multi-row interactive plot
    products = df['product'].dropna().unique()

    # Create a subplot grid (1 row per product)
    fig = make_subplots(rows=len(products), cols=1,
                        shared_xaxes=True, subplot_titles=products)

    for i, product in enumerate(products):
        row = i + 1
        prod_df = df[df['product'] == product]

        # Add Mid Price
        fig.add_trace(go.Scatter(x=prod_df['timestamp'], y=prod_df['mid_price'],
                                 mode='lines', name=f'{product} Mid', line=dict(color='black')), row=row, col=1)
        # Add PnL on a secondary y-axis style (scaled) or just overlaid
        fig.add_trace(go.Scatter(x=prod_df['timestamp'], y=prod_df['profit_and_loss'],
                                 mode='lines', name=f'{product} PnL', line=dict(color='blue', dash='dot')), row=row, col=1)

    fig.update_layout(height=400 * len(products),
                      title_text="Prosperity 4 Backtest Results", hovermode="x unified")

    # 4. Show the plot (Pops open in browser, then script ends)
    fig.show()


if __name__ == "__main__":
    plot_latest_run()
