"""
Plot step count data for Ranjit Sharma from Supabase.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from app.config import settings
from supabase import create_client

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# Fetch step data
pid = "11111111-1111-1111-1111-111111111111"
sixty_days_ago = (datetime.now() - timedelta(days=60)).date().isoformat()

resp = sb.table("vitals_daily") \
    .select("date, total_steps") \
    .eq("patient_id", pid) \
    .gte("date", sixty_days_ago) \
    .order("date") \
    .execute()

dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in resp.data]
steps = [r["total_steps"] for r in resp.data]

# Compute baseline (mean of first 30 days, excluding today)
import statistics
baseline_values = steps[:30]
baseline_mean = statistics.mean(baseline_values)
baseline_std = statistics.stdev(baseline_values) if len(baseline_values) > 1 else 0

# Thresholds
tudor_locke_floor = 1000
z2_threshold = baseline_mean - 2 * baseline_std

# --- Plot ---
fig, ax = plt.subplots(figsize=(14, 6))
fig.patch.set_facecolor('#0d1117')
ax.set_facecolor('#0d1117')

# Step data as area fill + line
ax.fill_between(dates, steps, alpha=0.15, color='#58a6ff')
ax.plot(dates, steps, color='#58a6ff', linewidth=2, marker='o', markersize=4, label='Daily Steps', zorder=3)

# Baseline mean
ax.axhline(y=baseline_mean, color='#8b949e', linestyle='--', linewidth=1.5, alpha=0.7, label=f'Baseline Mean ({baseline_mean:.0f})')

# Tudor-Locke floor (1000 steps)
ax.axhline(y=tudor_locke_floor, color='#f85149', linestyle='-', linewidth=2, alpha=0.8, label='Tudor-Locke Floor (1,000)')
ax.fill_between(dates, 0, tudor_locke_floor, alpha=0.08, color='#f85149')

# z-score = 2 threshold
if z2_threshold > tudor_locke_floor:
    ax.axhline(y=z2_threshold, color='#d29922', linestyle=':', linewidth=1.5, alpha=0.7, label=f'2 SD Below Baseline ({z2_threshold:.0f})')

# Highlight danger zone days
for i, (d, s) in enumerate(zip(dates, steps)):
    if s < tudor_locke_floor:
        ax.scatter([d], [s], color='#f85149', s=80, zorder=5, edgecolors='white', linewidth=1.5)
    elif z2_threshold > 0 and s < z2_threshold:
        ax.scatter([d], [s], color='#d29922', s=60, zorder=5, edgecolors='white', linewidth=1)

# Annotations
min_steps = min(steps)
min_idx = steps.index(min_steps)
ax.annotate(f'{int(min_steps)} steps\n(lowest)',
            xy=(dates[min_idx], min_steps),
            xytext=(dates[min_idx] - timedelta(days=5), min_steps + 800),
            fontsize=9, color='#f85149', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#f85149', lw=1.5),
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#161b22', edgecolor='#f85149', alpha=0.9))

# Styling
ax.set_title("Ranjit Sharma — Daily Step Count (60 Days)", fontsize=16, fontweight='bold', color='white', pad=15)
ax.set_xlabel("Date", fontsize=12, color='#8b949e')
ax.set_ylabel("Steps", fontsize=12, color='#8b949e')

ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
plt.xticks(rotation=45, ha='right')

ax.tick_params(colors='#8b949e')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_color('#30363d')
ax.spines['bottom'].set_color('#30363d')
ax.grid(axis='y', color='#21262d', linewidth=0.5)

legend = ax.legend(loc='upper right', fontsize=9, facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')

ax.set_ylim(bottom=0)

plt.tight_layout()

out_path = r"C:\Users\abhin\.gemini\antigravity-ide\brain\ef01e5f5-d0fd-465f-9fed-ab15d7df7cdd\step_count_chart.png"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
plt.savefig(out_path, dpi=150, facecolor='#0d1117', bbox_inches='tight')
print(f"Chart saved to {out_path}")
plt.close()
