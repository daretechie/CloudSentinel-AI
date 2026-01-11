<!--
  GreenOps Dashboard - Carbon Footprint & Sustainability
  
  Features:
  - Carbon footprint tracking (Scope 2 + Scope 3)
  - Carbon efficiency score
  - Green region recommendations
  - Graviton migration opportunities
  - Carbon budget monitoring
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { PUBLIC_API_URL } from '$env/static/public';
  import { createSupabaseBrowserClient } from '$lib/supabase';
  
  export let data;
  
  const supabase = createSupabaseBrowserClient();
  
  // State
  let carbonData: any = null;
  let gravitonData: any = null;
  let budgetData: any = null;
  let loading = true;
  let error = '';
  let selectedRegion = 'us-east-1';
  
  // Date range (default: last 30 days for faster loading)
  const today = new Date();
  const thirtyDaysAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
  const startDate = thirtyDaysAgo.toISOString().split('T')[0];
  const endDate = today.toISOString().split('T')[0];
  
  async function getAuthHeaders(): Promise<Record<string, string> | null> {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      error = 'Not authenticated. Please log in.';
      return null;
    }
    return {
      'Authorization': `Bearer ${session.access_token}`,
    };
  }
  
  async function fetchCarbonData() {
    const headers = await getAuthHeaders();
    if (!headers) return;
    
    try {
      const res = await fetch(
        `${PUBLIC_API_URL}/carbon?start_date=${startDate}&end_date=${endDate}&region=${selectedRegion}`,
        { headers }
      );
      if (res.ok) {
        carbonData = await res.json();
      } else if (res.status === 401) {
        error = 'Session expired. Please refresh the page.';
      } else {
        error = 'Failed to fetch carbon data';
      }
    } catch (e) {
      error = 'Network error fetching carbon data';
    }
  }
  
  async function fetchGravitonData() {
    const headers = await getAuthHeaders();
    if (!headers) return;
    
    try {
      const res = await fetch(
        `${PUBLIC_API_URL}/graviton?region=${selectedRegion}`,
        { headers }
      );
      if (res.ok) {
        gravitonData = await res.json();
      }
    } catch (e) {
      console.error('Failed to fetch Graviton data');
    }
  }
  
  async function fetchBudgetData() {
    const headers = await getAuthHeaders();
    if (!headers) return;
    
    try {
      const res = await fetch(
        `${PUBLIC_API_URL}/carbon/budget?region=${selectedRegion}`,
        { headers }
      );
      if (res.ok) {
        budgetData = await res.json();
      }
    } catch (e) {
      console.error('Failed to fetch budget data');
    }
  }
  
  async function loadAllData() {
    loading = true;
    error = '';
    await Promise.all([fetchCarbonData(), fetchGravitonData(), fetchBudgetData()]);
    loading = false;
  }
  
  onMount(async () => {
    if (data.user) {
      await loadAllData();
    } else {
      loading = false;
      error = 'Please log in to view GreenOps data.';
    }
  });
  
  // Format CO2 value
  function formatCO2(kg: number): string {
    if (kg < 1) return `${(kg * 1000).toFixed(1)} g`;
    if (kg < 1000) return `${kg.toFixed(2)} kg`;
    return `${(kg / 1000).toFixed(2)} t`;
  }
</script>

<svelte:head>
  <title>GreenOps - CloudSentinel</title>
</svelte:head>

<div class="space-y-6">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-2xl font-bold text-white">🌱 GreenOps Dashboard</h1>
      <p class="text-ink-400 mt-1">Monitor your cloud carbon footprint and sustainability</p>
    </div>
    
    <select 
      bind:value={selectedRegion}
      on:change={() => loadAllData()}
      class="bg-ink-800 border border-ink-700 rounded-lg px-3 py-2 text-sm"
    >
      <option value="us-east-1">US East (N. Virginia)</option>
      <option value="us-west-2">US West (Oregon)</option>
      <option value="eu-west-1">EU (Ireland)</option>
      <option value="eu-north-1">EU (Stockholm)</option>
      <option value="ap-northeast-1">Asia Pacific (Tokyo)</option>
    </select>
  </div>
  
  {#if loading}
    <div class="flex items-center justify-center py-20">
      <div class="animate-spin rounded-full h-8 w-8 border-t-2 border-accent-500"></div>
    </div>
  {:else if error}
    <div class="card bg-red-900/20 border-red-800 p-6">
      <p class="text-red-400">{error}</p>
    </div>
  {:else}
    <!-- Carbon Budget Status -->
    {#if budgetData && !budgetData.error}
      <div class="card p-6" class:budget-ok={budgetData.alert_status === 'ok'} 
           class:budget-warning={budgetData.alert_status === 'warning'}
           class:budget-exceeded={budgetData.alert_status === 'exceeded'}>
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold">Carbon Budget Status</h2>
          <span class="badge" class:badge-success={budgetData.alert_status === 'ok'}
                class:badge-warning={budgetData.alert_status === 'warning'}
                class:badge-error={budgetData.alert_status === 'exceeded'}>
            {budgetData.alert_status === 'ok' ? '✓ On Track' : 
             budgetData.alert_status === 'warning' ? '⚠️ Warning' : '🚨 Exceeded'}
          </span>
        </div>
        
        <!-- Progress Bar -->
        <div class="w-full bg-ink-800 rounded-full h-4 mb-3">
          <div 
            class="h-4 rounded-full transition-all"
            class:bg-green-500={budgetData.alert_status === 'ok'}
            class:bg-yellow-500={budgetData.alert_status === 'warning'}
            class:bg-red-500={budgetData.alert_status === 'exceeded'}
            style="width: {Math.min(budgetData.usage_percent, 100)}%"
          ></div>
        </div>
        
        <div class="flex justify-between text-sm text-ink-400">
          <span>{formatCO2(budgetData.current_usage_kg)} used</span>
          <span>{budgetData.usage_percent}% of {formatCO2(budgetData.budget_kg)} budget</span>
        </div>
      </div>
    {/if}
    
    <!-- Main Stats Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Total CO2 -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="text-2xl">🌍</span>
          <span class="text-ink-400 text-sm">Total Carbon Footprint</span>
        </div>
        <p class="text-3xl font-bold text-white">
          {carbonData ? formatCO2(carbonData.total_co2_kg) : '—'}
        </p>
        <p class="text-xs text-ink-500 mt-1">Scope 2 + Scope 3 emissions</p>
      </div>
      
      <!-- Carbon Efficiency -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="text-2xl">📈</span>
          <span class="text-ink-400 text-sm">Carbon Efficiency</span>
        </div>
        <p class="text-3xl font-bold text-white">
          {carbonData ? carbonData.carbon_efficiency_score : '—'}
          <span class="text-lg text-ink-400">gCO₂/$</span>
        </p>
        <p class="text-xs text-ink-500 mt-1">Lower is better</p>
      </div>
      
      <!-- Energy Usage -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="text-2xl">⚡</span>
          <span class="text-ink-400 text-sm">Estimated Energy</span>
        </div>
        <p class="text-3xl font-bold text-white">
          {carbonData ? carbonData.estimated_energy_kwh.toFixed(2) : '—'}
          <span class="text-lg text-ink-400">kWh</span>
        </p>
        <p class="text-xs text-ink-500 mt-1">Including PUE overhead</p>
      </div>
      
      <!-- Graviton Opportunities -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="text-2xl">🚀</span>
          <span class="text-ink-400 text-sm">Graviton Opportunities</span>
        </div>
        <p class="text-3xl font-bold text-white">
          {gravitonData && !gravitonData.error ? gravitonData.migration_candidates : '—'}
        </p>
        <p class="text-xs text-ink-500 mt-1">Instances for 40-60% savings</p>
      </div>
    </div>
    
    <!-- Scope Breakdown & Equivalencies -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Emissions Breakdown -->
      <div class="card p-6">
        <h3 class="text-lg font-semibold mb-4">📊 Emissions Breakdown</h3>
        
        {#if carbonData}
          <div class="space-y-4">
            <div>
              <div class="flex justify-between text-sm mb-1">
                <span class="text-ink-400">Scope 2 (Operational)</span>
                <span class="text-white">{formatCO2(carbonData.scope2_co2_kg)}</span>
              </div>
              <div class="w-full bg-ink-800 rounded-full h-2">
                <div class="bg-blue-500 h-2 rounded-full" 
                     style="width: {carbonData.total_co2_kg > 0 ? (carbonData.scope2_co2_kg / carbonData.total_co2_kg * 100) : 0}%"></div>
              </div>
            </div>
            
            <div>
              <div class="flex justify-between text-sm mb-1">
                <span class="text-ink-400">Scope 3 (Embodied)</span>
                <span class="text-white">{formatCO2(carbonData.scope3_co2_kg)}</span>
              </div>
              <div class="w-full bg-ink-800 rounded-full h-2">
                <div class="bg-purple-500 h-2 rounded-full" 
                     style="width: {carbonData.total_co2_kg > 0 ? (carbonData.scope3_co2_kg / carbonData.total_co2_kg * 100) : 0}%"></div>
              </div>
            </div>
          </div>
          
          <div class="mt-4 pt-4 border-t border-ink-800">
            <p class="text-xs text-ink-500">
              Region: {carbonData.region} ({carbonData.carbon_intensity_gco2_kwh} gCO₂/kWh)
            </p>
            <p class="text-xs text-ink-500">
              Methodology: {carbonData.methodology}
            </p>
          </div>
        {/if}
      </div>
      
      <!-- Equivalencies -->
      <div class="card p-6">
        <h3 class="text-lg font-semibold mb-4">🌲 Environmental Impact</h3>
        
        {#if carbonData?.equivalencies}
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-ink-800/50 rounded-lg p-4 text-center">
              <p class="text-2xl mb-1">🚗</p>
              <p class="text-xl font-bold text-white">{carbonData.equivalencies.miles_driven}</p>
              <p class="text-xs text-ink-400">miles driven</p>
            </div>
            
            <div class="bg-ink-800/50 rounded-lg p-4 text-center">
              <p class="text-2xl mb-1">🌳</p>
              <p class="text-xl font-bold text-white">{carbonData.equivalencies.trees_needed_for_year}</p>
              <p class="text-xs text-ink-400">trees needed/year</p>
            </div>
            
            <div class="bg-ink-800/50 rounded-lg p-4 text-center">
              <p class="text-2xl mb-1">📱</p>
              <p class="text-xl font-bold text-white">{carbonData.equivalencies.smartphone_charges}</p>
              <p class="text-xs text-ink-400">phone charges</p>
            </div>
            
            <div class="bg-ink-800/50 rounded-lg p-4 text-center">
              <p class="text-2xl mb-1">🏠</p>
              <p class="text-xl font-bold text-white">{carbonData.equivalencies.percent_of_home_month}%</p>
              <p class="text-xs text-ink-400">of avg home/month</p>
            </div>
          </div>
        {/if}
      </div>
    </div>
    
    <!-- Green Region Recommendations -->
    {#if carbonData?.green_region_recommendations?.length > 0}
      <div class="card p-6">
        <h3 class="text-lg font-semibold mb-4">🌿 Greener Region Alternatives</h3>
        <p class="text-ink-400 text-sm mb-4">
          Consider migrating workloads to these lower-carbon regions:
        </p>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          {#each carbonData.green_region_recommendations.slice(0, 3) as rec}
            <div class="bg-green-900/20 border border-green-800 rounded-lg p-4">
              <p class="font-semibold text-white">{rec.region}</p>
              <p class="text-green-400 text-sm">{rec.carbon_intensity} gCO₂/kWh</p>
              <p class="text-green-300 text-xs mt-1">↓ {rec.savings_percent}% less carbon</p>
            </div>
          {/each}
        </div>
      </div>
    {/if}
    
    <!-- Graviton Migration Candidates -->
    {#if gravitonData && gravitonData.candidates?.length > 0}
      <div class="card p-6">
        <h3 class="text-lg font-semibold mb-4">🚀 Graviton Migration Candidates</h3>
        <p class="text-ink-400 text-sm mb-4">
          These EC2 instances can migrate to ARM for up to 60% energy savings:
        </p>
        
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-ink-400 border-b border-ink-800">
              <tr>
                <th class="text-left py-2">Instance</th>
                <th class="text-left py-2">Current Type</th>
                <th class="text-left py-2">Recommended</th>
                <th class="text-left py-2">Energy Savings</th>
              </tr>
            </thead>
            <tbody>
              {#each gravitonData.candidates.slice(0, 5) as candidate}
                <tr class="border-b border-ink-800/50">
                  <td class="py-3 text-white">{candidate.name || candidate.instance_id}</td>
                  <td class="py-3 text-ink-400">{candidate.current_type}</td>
                  <td class="py-3 text-green-400">{candidate.recommended_type}</td>
                  <td class="py-3 text-green-400">↓ {candidate.energy_savings_percent}%</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .card {
    background-color: var(--color-ink-900);
    border: 1px solid var(--color-ink-800);
    border-radius: 0.75rem;
  }
  
  .badge-success {
    background-color: rgb(34 197 94 / 0.2);
    color: rgb(74 222 128);
  }
  
  .badge-warning {
    background-color: rgb(234 179 8 / 0.2);
    color: rgb(250 204 21);
  }
  
  .badge-error {
    background-color: rgb(239 68 68 / 0.2);
    color: rgb(248 113 113);
  }
  
  .budget-ok {
    background-color: rgb(34 197 94 / 0.1);
    border-color: rgb(34 197 94 / 0.3);
  }
  
  .budget-warning {
    background-color: rgb(234 179 8 / 0.1);
    border-color: rgb(234 179 8 / 0.3);
  }
  
  .budget-exceeded {
    background-color: rgb(239 68 68 / 0.1);
    border-color: rgb(239 68 68 / 0.3);
  }
</style>
