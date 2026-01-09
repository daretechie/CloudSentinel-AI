<!--
  Dashboard Home Page - Premium SaaS Design
  
  Features:
  - Stats cards with motion animations
  - Staggered entrance effects
  - Clean data visualization
  - Loading skeletons
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { PUBLIC_API_URL } from '$env/static/public';
  import { createSupabaseBrowserClient } from '$lib/supabase';
  
  export let data;
  
  const supabase = createSupabaseBrowserClient();
  
  let loading = true;
  let costs: any = null;
  let carbon: any = null;
  let zombies: any = null;
  let error = '';
  
  const endDate = new Date().toISOString().split('T')[0];
  const startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  
  onMount(async () => {
    if (!data.user) {
      loading = false;
      return;
    }
    
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      
      const headers = {
        'Authorization': `Bearer ${session.access_token}`,
      };
      
      const [costsRes, carbonRes, zombiesRes] = await Promise.all([
        fetch(`${PUBLIC_API_URL}/costs?start_date=${startDate}&end_date=${endDate}`, { headers }),
        fetch(`${PUBLIC_API_URL}/carbon?start_date=${startDate}&end_date=${endDate}`, { headers }),
        fetch(`${PUBLIC_API_URL}/zombies`, { headers }),
      ]);
      
      costs = await costsRes.json();
      carbon = await carbonRes.json();
      zombies = await zombiesRes.json();
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  });
  
  // Calculate zombie count
  $: zombieCount = (zombies?.unattached_volumes?.length ?? 0) + 
                   (zombies?.old_snapshots?.length ?? 0) + 
                   (zombies?.unused_elastic_ips?.length ?? 0);
</script>

<svelte:head>
  <title>Dashboard | CloudSentinel</title>
</svelte:head>

{#if !data.user}
  <!-- Public Landing -->
  <div class="min-h-[80vh] flex flex-col items-center justify-center text-center px-4">
    <div class="stagger-enter" style="animation-delay: 0ms;">
      <span class="text-6xl mb-4 block">☁️</span>
    </div>
    <h1 class="text-4xl md:text-5xl font-bold mb-4 stagger-enter" style="animation-delay: 100ms;">
      Cloud Cost Intelligence
    </h1>
    <p class="text-xl text-ink-400 mb-8 max-w-lg stagger-enter" style="animation-delay: 200ms;">
      AI-powered FinOps platform that tracks costs, carbon footprint, and zombie resources.
    </p>
    <a href="/auth/login" class="btn btn-primary text-lg px-8 py-3 stagger-enter" style="animation-delay: 300ms;">
      Get Started Free
    </a>
  </div>
{:else}
  <div class="space-y-8">
    <!-- Page Header -->
    <div>
      <h1 class="text-2xl font-bold mb-1">Dashboard</h1>
      <p class="text-ink-400 text-sm">Overview of your cloud infrastructure</p>
    </div>
    
    {#if loading}
      <!-- Loading Skeletons -->
      <div class="grid gap-5 md:grid-cols-2 lg:grid-cols-4">
        {#each [1, 2, 3, 4] as i}
          <div class="card" style="animation-delay: {i * 50}ms;">
            <div class="skeleton h-4 w-20 mb-3"></div>
            <div class="skeleton h-8 w-32"></div>
          </div>
        {/each}
      </div>
    {:else if error}
      <div class="card border-danger-500/50 bg-danger-500/10">
        <p class="text-danger-400">{error}</p>
      </div>
    {:else}
      <!-- Stats Grid -->
      <div class="grid gap-5 md:grid-cols-2 lg:grid-cols-4">
        <!-- 30-Day Cost -->
        <div class="card card-stat stagger-enter" style="animation-delay: 0ms;">
          <p class="text-sm text-ink-400 mb-1">30-Day Cost</p>
          <p class="text-3xl font-bold" style="color: var(--color-accent-400);">
            ${costs?.total_cost?.toFixed(2) ?? '0.00'}
          </p>
          <p class="text-xs text-ink-500 mt-2">
            vs last period
          </p>
        </div>
        
        <!-- Carbon Footprint -->
        <div class="card card-stat stagger-enter" style="animation-delay: 50ms;">
          <p class="text-sm text-ink-400 mb-1">Carbon Footprint</p>
          <p class="text-3xl font-bold" style="color: var(--color-success-400);">
            {carbon?.total_co2_kg?.toFixed(2) ?? '0.00'} kg
          </p>
          <p class="text-xs text-ink-500 mt-2">
            CO₂ emissions
          </p>
        </div>
        
        <!-- Zombie Resources -->
        <div class="card card-stat stagger-enter" style="animation-delay: 100ms;">
          <p class="text-sm text-ink-400 mb-1">Zombie Resources</p>
          <p class="text-3xl font-bold" style="color: var(--color-warning-400);">
            {zombieCount}
          </p>
          <p class="text-xs text-ink-500 mt-2">
            Unused resources found
          </p>
        </div>
        
        <!-- Monthly Waste -->
        <div class="card card-stat stagger-enter" style="animation-delay: 150ms;">
          <p class="text-sm text-ink-400 mb-1">Monthly Waste</p>
          <p class="text-3xl font-bold" style="color: var(--color-danger-400);">
            ${zombies?.total_monthly_waste?.toFixed(2) ?? '0.00'}
          </p>
          <p class="text-xs text-ink-500 mt-2">
            Potential savings
          </p>
        </div>
      </div>
      
      <!-- Carbon Impact Section -->
      {#if carbon?.equivalencies}
        <div class="card stagger-enter" style="animation-delay: 200ms;">
          <h2 class="text-lg font-semibold mb-5">Carbon Impact</h2>
          <div class="grid gap-6 md:grid-cols-4 text-center">
            <div class="p-4 rounded-lg bg-ink-800/50">
              <p class="text-2xl font-bold text-ink-100">{carbon.equivalencies.miles_driven}</p>
              <p class="text-sm text-ink-400 mt-1">Miles Driven</p>
            </div>
            <div class="p-4 rounded-lg bg-ink-800/50">
              <p class="text-2xl font-bold text-ink-100">{carbon.equivalencies.trees_needed_for_year}</p>
              <p class="text-sm text-ink-400 mt-1">Trees Needed</p>
            </div>
            <div class="p-4 rounded-lg bg-ink-800/50">
              <p class="text-2xl font-bold text-ink-100">{carbon.equivalencies.smartphone_charges}</p>
              <p class="text-sm text-ink-400 mt-1">Phone Charges</p>
            </div>
            <div class="p-4 rounded-lg bg-ink-800/50">
              <p class="text-2xl font-bold text-ink-100">{carbon.equivalencies.percent_of_home_month}%</p>
              <p class="text-sm text-ink-400 mt-1">Of Home/Month</p>
            </div>
          </div>
        </div>
      {/if}
      
      <!-- Zombie Resources Table -->
      {#if zombieCount > 0}
        <div class="card stagger-enter" style="animation-delay: 250ms;">
          <div class="flex items-center justify-between mb-5">
            <h2 class="text-lg font-semibold">Zombie Resources</h2>
            <span class="badge badge-warning">{zombieCount} found</span>
          </div>
          
          <div class="overflow-x-auto">
            <table class="table">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Type</th>
                  <th>Monthly Cost</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {#each zombies?.unattached_volumes ?? [] as vol}
                  <tr>
                    <td class="font-mono text-xs">{vol.resource_id}</td>
                    <td><span class="badge badge-default">EBS Volume</span></td>
                    <td class="text-danger-400">${vol.monthly_cost}</td>
                    <td>
                      <button class="btn btn-ghost text-xs">Review</button>
                    </td>
                  </tr>
                {/each}
                {#each zombies?.old_snapshots ?? [] as snap}
                  <tr>
                    <td class="font-mono text-xs">{snap.resource_id}</td>
                    <td><span class="badge badge-default">Snapshot</span></td>
                    <td class="text-danger-400">${snap.monthly_cost}</td>
                    <td>
                      <button class="btn btn-ghost text-xs">Review</button>
                    </td>
                  </tr>
                {/each}
                {#each zombies?.unused_elastic_ips ?? [] as eip}
                  <tr>
                    <td class="font-mono text-xs">{eip.resource_id}</td>
                    <td><span class="badge badge-default">Elastic IP</span></td>
                    <td class="text-danger-400">${eip.monthly_cost}</td>
                    <td>
                      <button class="btn btn-ghost text-xs">Review</button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .text-ink-400 { color: var(--color-ink-400); }
  .text-ink-500 { color: var(--color-ink-500); }
  .text-ink-100 { color: var(--color-ink-100); }
  .bg-ink-800\/50 { background-color: rgb(24 32 40 / 0.5); }
  .text-danger-400 { color: var(--color-danger-400); }
  .border-danger-500\/50 { border-color: rgb(244 63 94 / 0.5); }
  .bg-danger-500\/10 { background-color: rgb(244 63 94 / 0.1); }
</style>
