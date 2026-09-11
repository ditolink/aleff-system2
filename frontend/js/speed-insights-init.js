// Vercel Speed Insights initialization
// This file initializes Vercel Speed Insights for tracking web performance metrics
import { injectSpeedInsights } from './speed-insights.mjs';

// Initialize Speed Insights
// The script will automatically track Core Web Vitals and other performance metrics
injectSpeedInsights({
  debug: false, // Set to true in development if you want to see debug logs
  sampleRate: 1, // Track 100% of page views (adjust if needed for high traffic sites)
});
