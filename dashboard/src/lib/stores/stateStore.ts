/**
 * State Store - Frontend State Persistence
 * 
 * Solves Due Diligence Finding #5: Fragile Frontend State
 * 
 * Features:
 * - localStorage persistence for form state
 * - Auto-save with debouncing
 * - Unsaved changes detection
 * - Session recovery on page refresh
 */

type StateStoreOptions = {
  key: string;
  debounceMs?: number;
  expiryHours?: number;
};

type StoredValue<T> = {
  value: T;
  timestamp: number;
  version: number;
};

const STORE_VERSION = 1;
const DEFAULT_DEBOUNCE = 500;
const DEFAULT_EXPIRY_HOURS = 24;

/**
 * Create a persistent state store with localStorage backup.
 */
export function createStateStore<T>(options: StateStoreOptions) {
  const { 
    key, 
    debounceMs = DEFAULT_DEBOUNCE, 
    expiryHours = DEFAULT_EXPIRY_HOURS 
  } = options;
  
  const storageKey = `valdrix_state_${key}`;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let hasUnsavedChanges = false;
  
  /**
   * Load state from localStorage.
   */
  function load(): T | null {
    if (typeof window === 'undefined') return null;
    
    try {
      const stored = localStorage.getItem(storageKey);
      if (!stored) return null;
      
      const parsed: StoredValue<T> = JSON.parse(stored);
      
      // Check version
      if (parsed.version !== STORE_VERSION) {
        localStorage.removeItem(storageKey);
        return null;
      }
      
      // Check expiry
      const ageHours = (Date.now() - parsed.timestamp) / (1000 * 60 * 60);
      if (ageHours > expiryHours) {
        localStorage.removeItem(storageKey);
        return null;
      }
      
      return parsed.value;
    } catch {
      return null;
    }
  }
  
  /**
   * Save state to localStorage (debounced).
   */
  function save(value: T): void {
    if (typeof window === 'undefined') return;
    
    hasUnsavedChanges = true;
    
    // Debounce to avoid excessive writes
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    
    debounceTimer = setTimeout(() => {
      const stored: StoredValue<T> = {
        value,
        timestamp: Date.now(),
        version: STORE_VERSION
      };
      
      try {
        localStorage.setItem(storageKey, JSON.stringify(stored));
        hasUnsavedChanges = false;
      } catch (e) {
        console.warn('Failed to save state to localStorage:', e);
      }
    }, debounceMs);
  }
  
  /**
   * Immediately persist state (bypass debounce).
   */
  function saveNow(value: T): void {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    
    const stored: StoredValue<T> = {
      value,
      timestamp: Date.now(),
      version: STORE_VERSION
    };
    
    try {
      localStorage.setItem(storageKey, JSON.stringify(stored));
      hasUnsavedChanges = false;
    } catch (e) {
      console.warn('Failed to save state to localStorage:', e);
    }
  }
  
  /**
   * Clear stored state.
   */
  function clear(): void {
    if (typeof window === 'undefined') return;
    localStorage.removeItem(storageKey);
    hasUnsavedChanges = false;
  }
  
  /**
   * Check if there are unsaved changes.
   */
  function hasChanges(): boolean {
    return hasUnsavedChanges;
  }
  
  return {
    load,
    save,
    saveNow,
    clear,
    hasChanges
  };
}

/**
 * Hook to warn user about unsaved changes before leaving.
 */
export function setupUnsavedChangesWarning(getMessage: () => boolean): (() => void) | undefined {
  if (typeof window === 'undefined') return undefined;
  
  const handleBeforeUnload = (e: BeforeUnloadEvent) => {
    if (getMessage()) {
      e.preventDefault();
      e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
      return e.returnValue;
    }
  };
  
  window.addEventListener('beforeunload', handleBeforeUnload);
  
  // Return cleanup function
  return () => {
    window.removeEventListener('beforeunload', handleBeforeUnload);
  };
}

// Pre-configured stores for common forms
export const settingsStore = createStateStore<Record<string, unknown>>({ 
  key: 'settings',
  expiryHours: 1 
});

export const onboardingStore = createStateStore<Record<string, unknown>>({ 
  key: 'onboarding',
  expiryHours: 24 
});

export const remediationStore = createStateStore<Record<string, unknown>>({ 
  key: 'remediation',
  expiryHours: 1 
});
