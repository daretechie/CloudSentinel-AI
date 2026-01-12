# Valdrix Architecture

## System Overview

```mermaid
graph TB
    subgraph Frontend
        SvelteKit[SvelteKit Dashboard]
    end

    subgraph Backend["FastAPI Backend"]
        API[REST API]
        Auth[Supabase Auth]
        Scheduler[APScheduler Jobs]
        LLM[LLM Analyzer]
    end

    subgraph Services
        Zombies[Zombie Detector]
        Carbon[Carbon Calculator]
        Adapters[AWS Adapters]
    end

    subgraph External
        AWS[AWS APIs via STS]
        LLMProviders[LLM Providers]
        Supabase[(Supabase PostgreSQL)]
        Prometheus[Prometheus Metrics]
    end

    SvelteKit --> API
    API --> Auth
    API --> Zombies
    API --> Carbon
    API --> LLM
    Scheduler --> Adapters
    Scheduler --> Zombies
    Adapters --> AWS
    LLM --> LLMProviders
    API --> Supabase
    API --> Prometheus
```

## Component Descriptions

| Component | Description |
|-----------|-------------|
| **SvelteKit Dashboard** | User-facing web UI for viewing costs, zombies, carbon metrics |
| **FastAPI Backend** | Async Python API with Pydantic validation |
| **Supabase Auth** | JWT-based authentication and Row Level Security |
| **APScheduler Jobs** | Background jobs for daily scans and weekly remediation |
| **Zombie Detector** | Plugin-based detection of 11 AWS zombie resource types |
| **Carbon Calculator** | GreenOps metrics and Graviton migration recommendations |
| **LLM Analyzer** | AI-powered cost analysis via OpenAI/Claude/Groq |
| **AWS Adapters** | STS-based multi-tenant AWS access (no long-lived credentials) |

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Dashboard
    participant API
    participant Scheduler
    participant AWS
    participant LLM

    User->>Dashboard: View Zombie Resources
    Dashboard->>API: GET /zombies
    API->>AWS: STS AssumeRole
    AWS-->>API: Temporary Credentials
    API->>AWS: Describe Resources
    AWS-->>API: Resource Data
    API->>LLM: Analyze Costs
    LLM-->>API: Recommendations
    API-->>Dashboard: Zombie Report
    Dashboard-->>User: Display Results
```

## Security Model

- **Zero Trust**: No long-lived AWS credentials
- **STS AssumeRole**: Temporary credentials per request
- **Read-Only IAM**: Principle of least privilege
- **Human-in-the-Loop**: Remediation requires approval
- **Encrypted at Rest**: AES-256 via ENCRYPTION_KEY

## Plugin Architecture (Zombie Detection)

```
ZombiePlugin (ABC)
├── storage.py
│   ├── UnattachedVolumesPlugin
│   ├── OldSnapshotsPlugin
│   └── IdleS3BucketsPlugin
├── compute.py
│   ├── IdleInstancesPlugin
│   └── OrphanLoadBalancersPlugin
├── database.py
│   ├── IdleRdsPlugin
│   └── ColdRedshiftPlugin
├── network.py
│   ├── UnusedElasticIpsPlugin
│   └── UnderusedNatGatewaysPlugin
├── containers.py
│   └── LegacyEcrImagesPlugin
└── analytics.py
    └── IdleSageMakerPlugin
```
