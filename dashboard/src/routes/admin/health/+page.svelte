<script lang="ts">
  import { onMount } from 'svelte';
  import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { BarChart, Activity, ShieldCircle, Server } from 'lucide-svelte';
  
  let healthMetrics = {
    uptime: "99.98%",
    active_jobs: 0,
    failed_jobs: 0,
    llm_latency: "1.2s",
    db_connections: 0
  };

  let loading = true;

  onMount(async () => {
    // In a real implementation, this would fetch from /api/v1/health-dashboard
    // For now, we simulate a small delay
    setTimeout(() => {
      healthMetrics = {
        uptime: "99.95%",
        active_jobs: 12,
        failed_jobs: 2,
        llm_latency: "1.4s",
        db_connections: 8
      };
      loading = false;
    }, 500);
  });
</script>

<div class="p-8 space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-3xl font-bold tracking-tight">Investor Health Dashboard</h1>
    <Button variant="outline">
      <Activity class="mr-2 h-4 w-4" />
      Refresh Metrics
    </Button>
  </div>

  <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle class="text-sm font-medium">System Uptime</CardTitle>
        <Activity class="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{healthMetrics.uptime}</div>
        <p class="text-xs text-muted-foreground">+0.01% from yesterday</p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle class="text-sm font-medium">Background Jobs</CardTitle>
        <Server class="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{healthMetrics.active_jobs}</div>
        <p class="text-xs text-destructive">{healthMetrics.failed_jobs} failed in last 24h</p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle class="text-sm font-medium">LLM Performance</CardTitle>
        <ShieldCircle class="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{healthMetrics.llm_latency}</div>
        <p class="text-xs text-muted-foreground">p95 avg latency</p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle class="text-sm font-medium">Active DB Connections</CardTitle>
        <BarChart class="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{healthMetrics.db_connections}</div>
        <p class="text-xs text-muted-foreground">out of 20 pool max</p>
      </CardContent>
    </Card>
  </div>

  <Card class="mt-8">
    <CardHeader>
      <CardTitle>System Logs & Anomalies</CardTitle>
    </CardHeader>
    <CardContent>
      <div class="rounded-md border p-4 font-mono text-sm">
        <div class="text-blue-500">[INFO] 2026-01-16 10:45:00 - Job#7782 started: finops_analysis for tenant_123</div>
        <div class="text-green-500">[SUCCESS] 2026-01-16 10:44:55 - Webhook retry successful: Paystack#REF_9982</div>
        <div class="text-red-500">[ERROR] 2026-01-16 10:44:00 - Groq API Rate Limit Hit (Fallback to Gemini initialized)</div>
        <div class="text-yellow-500">[WARN] 2026-01-16 10:43:55 - Delta Analysis skipped: No previous cache found for tenant_445</div>
      </div>
    </CardContent>
  </Card>
</div>
