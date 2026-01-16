<!--
  Billing Page - Paystack Integration
  
  Features:
  - Current plan display with glassmorphism
  - Pricing tier cards
  - Upgrade flow integration
-->

<script lang="ts">
  import { PUBLIC_API_URL } from '$env/static/public';
  import { createSupabaseBrowserClient } from '$lib/supabase';
  
  let { data } = $props();
  
  const supabase = createSupabaseBrowserClient();
  
  let loading = $state(true);
  let subscription = $state<any>(null);
  let error = $state('');
  let upgrading = $state('');
  
  const prices = {
    starter: '$29',
    growth: '$79',
    pro: '$199',
    enterprise: 'Custom'
  };
  
  const features = {
    starter: ['Single Cloud (AWS)', 'Cost Dashboards', 'Budget Alerts', 'Basic Zombie Detection', 'Up to $10K cloud spend'],
    growth: ['Multi-Cloud Support', 'AI Cost Analysis', 'Full Zombie Detection', 'GreenOps (Carbon Tracking)', 'Slack Integration', 'Forecasting', 'Up to $50K cloud spend'],
    pro: ['Everything in Growth', 'Auto-Remediation', 'Full API Access', 'Priority Support', 'Up to $200K cloud spend'],
    enterprise: ['Unlimited Accounts', 'SSO (SAML/OIDC)', 'Dedicated Support', 'Custom SLA', 'Unlimited cloud spend']
  };
  
  $effect(() => {
    if (!data.user) {
      loading = false;
      return;
    }
    loadSubscription();
  });
  
  async function loadSubscription() {
    try {
      const session = data.session;
      if (!session) return;
      
      const res = await fetch(`${PUBLIC_API_URL}/billing/subscription`, {
        headers: { 'Authorization': `Bearer ${session.access_token}` }
      });
      
      if (res.ok) {
        subscription = await res.json();
      } else {
        subscription = { tier: 'free', status: 'active' };
      }
    } catch (e: any) {
      error = e.message;
      subscription = { tier: 'free', status: 'active' };
    } finally {
      loading = false;
    }
  }
  
  async function upgrade(tier: string) {
    if (upgrading) return;
    upgrading = tier;
    
    try {
      const session = data.session;
      if (!session) throw new Error('Not authenticated');
      
      const res = await fetch(`${PUBLIC_API_URL}/billing/checkout`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ tier })
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Checkout failed');
      }
      
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
      
    } catch (e: any) {
      error = e.message;
      upgrading = '';
    }
  }
  
  function tierIsCurrent(tier: string): boolean {
    return subscription?.tier?.toLowerCase() === tier.toLowerCase();
  }
</script>

<svelte:head>
  <title>Billing | Valdrix</title>
</svelte:head>

<div class="space-y-8">
  <!-- Page Header -->
  <div>
    <h1 class="text-2xl font-bold mb-1">Billing & Plans</h1>
    <p class="text-ink-400 text-sm">Manage your subscription and payment methods</p>
  </div>
  
  {#if !data.user}
    <div class="card text-center py-12">
      <p class="text-ink-400">Please <a href="/auth/login" class="text-accent-400 hover:underline">sign in</a> to manage billing.</p>
    </div>
  {:else if loading}
    <div class="grid gap-5 md:grid-cols-3">
      {#each [1, 2, 3] as i}
        <div class="card">
          <div class="skeleton h-6 w-24 mb-4"></div>
          <div class="skeleton h-10 w-32 mb-6"></div>
          <div class="skeleton h-8 w-full"></div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="card border-danger-500/50 bg-danger-500/10">
      <p class="text-danger-400">{error}</p>
    </div>
  {:else}
    <!-- Current Plan -->
    <div class="glass-panel pulse-glow stagger-enter" style="animation-delay: 0ms;">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-ink-400 mb-1">Current Plan</p>
          <p class="text-4xl font-bold text-gradient capitalize">{subscription?.tier || 'Free'}</p>
          <div class="flex items-center gap-2 mt-2">
            <span class="badge {subscription?.status === 'active' ? 'badge-success' : 'badge-warning'}">
              {subscription?.status || 'Active'}
            </span>
            {#if subscription?.next_payment_date}
              <span class="text-xs text-ink-500">
                Next billing: {new Date(subscription.next_payment_date).toLocaleDateString()}
              </span>
            {/if}
          </div>
        </div>
        <div class="hero-icon text-6xl">💳</div>
      </div>
    </div>
    
    <!-- Pricing Tiers -->
    <div class="grid gap-5 md:grid-cols-4">
      {#each ['starter', 'growth', 'pro', 'enterprise'] as tier, i}
        <div 
          class="card stagger-enter {tierIsCurrent(tier) ? 'border-accent-500 border-2' : ''}" 
          style="animation-delay: {50 + i * 50}ms;"
        >
          <!-- Tier Header -->
          <div class="mb-4">
            <h3 class="text-lg font-semibold capitalize">{tier}</h3>
            <p class="text-3xl font-bold mt-2">
              {prices[tier as keyof typeof prices]}
              {#if tier !== 'enterprise'}
                <span class="text-sm text-ink-400 font-normal">/month</span>
              {/if}
            </p>
          </div>
          
          <!-- Features -->
          <ul class="space-y-2 mb-6">
            {#each features[tier as keyof typeof features] as feature}
              <li class="flex items-center gap-2 text-sm text-ink-300">
                <span class="text-success-400">✓</span>
                {feature}
              </li>
            {/each}
          </ul>
          
          <!-- Action Button -->
          {#if tierIsCurrent(tier)}
            <button class="btn btn-secondary w-full" disabled>
              Current Plan
            </button>
          {:else if tier === 'enterprise'}
            <a href="mailto:enterprise@valdrix.io" class="btn btn-secondary w-full text-center">
              Contact Sales
            </a>
          {:else}
            <button 
              class="btn btn-primary w-full"
              onclick={() => upgrade(tier)}
              disabled={!!upgrading}
            >
              {#if upgrading === tier}
                <span class="spinner"></span>
                Processing...
              {:else}
                Upgrade to {tier}
              {/if}
            </button>
          {/if}
        </div>
      {/each}
    </div>
    
    <!-- Payment Info -->
    <div class="card stagger-enter text-center" style="animation-delay: 250ms;">
      <h3 class="text-lg font-semibold mb-3">Payment Information</h3>
      <div class="flex items-center justify-center gap-4 text-sm text-ink-400">
        <span>Powered by</span>
        <span class="font-bold text-ink-200">Paystack</span>
        <span>•</span>
        <span>Secure payment processing</span>
      </div>
      <p class="text-xs text-ink-500 mt-2">
        All payments are processed securely. You can cancel your subscription at any time.
      </p>
    </div>
  {/if}
</div>

<style>
  .border-accent-500 { border-color: var(--color-accent-500); }
</style>
