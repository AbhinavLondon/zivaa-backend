from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import datetime

local_tz = datetime.datetime.now().astimezone().tzinfo
scheduler = AsyncIOScheduler(timezone=local_tz)

async def start_scheduler():
    scheduler.start()
    print("APScheduler started.")

async def stop_scheduler():
    scheduler.shutdown()
    print("APScheduler stopped.")

def setup_cron_jobs():
    from app.services.scheduler_jobs import run_morning_fallback, run_daily_longevity_fallback, run_weekly_caregiver_digest, run_midday_checkins, run_evening_checkins,
    scheduler.add_job(
        run_latenight_checkins,
        'cron',
        minute=5, # run at XX:05
        id='latenight_checkins_job',
        replace_existing=True,
        misfire_grace_time=None
    )
 run_latenight_checkins, run_weekly_planning, run_weekly_longevity_strategy, run_weekly_retest_digest
    
    # Run daily longevity fallback
    scheduler.add_job(
        run_daily_longevity_fallback,
        'cron',
        hour=9, # 9 AM local time
        minute=0,
        id='daily_longevity_fallback_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run morning fallback (Target: 9:00 AM local time)
    scheduler.add_job(
        run_morning_fallback,
        'cron',
        minute='*/15',
        id='morning_fallback_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run mid-day checkin (Target: 12:00 PM local time)
    scheduler.add_job(
        run_midday_checkins,
        'cron',
        minute='*/15',
        id='midday_checkins_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run evening checkin (Target: 8:00 PM local time)
    scheduler.add_job(
        run_evening_checkins,
    scheduler.add_job(
        run_latenight_checkins,
        'cron',
        minute=5, # run at XX:05
        id='latenight_checkins_job',
        replace_existing=True,
        misfire_grace_time=None
    )

        'cron',
        minute='*/15',
        id='evening_checkins_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run weekly re-test digest
    scheduler.add_job(
        run_weekly_retest_digest,
        'cron',
        day_of_week='sat',
        hour=10, # Will be filtered in job to be local time 10AM
        minute=0,
        id='weekly_retest_digest_job',
        replace_existing=True
    )
    
    # Run weekly caregiver digest (Target: Sunday 10:00 AM local time)
    scheduler.add_job(
        run_weekly_caregiver_digest,
        'cron',
        minute='*/15',
        id='weekly_caregiver_digest',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run weekly positive reinforcement digest (Target: Sunday 10:00 AM local time)
    from app.services.scheduler_jobs import run_weekly_patient_reinforcement
    scheduler.add_job(
        run_weekly_patient_reinforcement,
        'cron',
        minute='*/15',
        id='weekly_patient_reinforcement',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run batch pattern detection (Target: 11:00 PM local time)
    from app.services.scheduler_jobs import run_batch_pattern_detection
    scheduler.add_job(
        run_batch_pattern_detection,
        'cron',
        minute='*/15',
        id='batch_pattern_detection',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run morning nudge dispatch (Target: 8:00 AM local time)
    from app.services.scheduler_jobs import run_morning_nudge_dispatch
    scheduler.add_job(
        run_morning_nudge_dispatch,
        'cron',
        minute='*/15',
        id='morning_nudge_dispatch',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run memory extraction every 5 minutes
    from app.services.scheduler_jobs import run_memory_extraction
    scheduler.add_job(
        run_memory_extraction,
        'cron',
        minute='*/5',
        id='memory_extraction_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run proactive memory follow-ups every hour
    from app.services.scheduler_jobs import run_proactive_followups
    scheduler.add_job(
        run_proactive_followups,
        'cron',
        minute=30, # Run at half past the hour to spread load
        id='proactive_followups_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run weekly planning on Sunday morning (e.g. 8:00 AM)
    scheduler.add_job(
        run_weekly_planning,
        'cron',
        day_of_week='sun',
        hour=8,
        minute=0,
        id='weekly_planning_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run weekly longevity strategy on Sunday morning (e.g. 7:00 AM)
    scheduler.add_job(
        run_weekly_longevity_strategy,
        'cron',
        day_of_week='sun',
        hour=7,
        minute=0,
        id='weekly_longevity_strategy_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run memory consolidation nightly (Target: 2:00 AM local time)
    from app.services.scheduler_jobs import run_memory_consolidation
    scheduler.add_job(
        run_memory_consolidation,
        'cron',
        hour=2,
        minute=0,
        id='memory_consolidation_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    # Run nightly nutritional analysis (Target: 1:00 AM local time)
    from app.services.scheduler_jobs import run_nightly_nutritional_analysis
    scheduler.add_job(
        run_nightly_nutritional_analysis,
        'cron',
        hour=1,
        minute=0,
        id='nightly_nutritional_analysis_job',
        replace_existing=True,
        misfire_grace_time=None
    )
    
    print("Cron jobs configured.")
