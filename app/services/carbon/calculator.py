"""
Carbon Footprint Calculator

Estimates CO₂ emissions from AWS cloud usage based on:
1. AWS region (electricity grid carbon intensity)
2. Service type (compute, storage, networking)
3. Cost as a proxy for resource consumption

References:
- AWS Customer Carbon Footprint Tool methodology
- Cloud Carbon Footprint (CCF) open source project
- EPA emissions factors
"""

from typing import List, Dict, Any
from decimal import Decimal
import structlog

logger = structlog.get_logger()


# Carbon intensity by AWS region (gCO₂eq per kWh)
# Source: Electricity Maps, EPA eGRID, and AWS sustainability reports
REGION_CARBON_INTENSITY = {
    # Low carbon (renewables/nuclear)
    "us-west-2": 21,      # Oregon - hydro
    "eu-north-1": 28,     # Stockholm - hydro/nuclear
    "ca-central-1": 35,   # Montreal - hydro
    "eu-west-1": 316,     # Ireland - wind/gas mix
    
    # Medium carbon
    "us-west-1": 218,     # N. California
    "eu-west-2": 225,     # London
    "eu-central-1": 338,  # Frankfurt
    
    # High carbon (coal/gas heavy)
    "us-east-1": 379,     # N. Virginia
    "us-east-2": 440,     # Ohio
    "ap-southeast-1": 408,# Singapore
    "ap-south-1": 708,    # Mumbai
    "ap-northeast-1": 506,# Tokyo
    
    # Default for unknown regions
    "default": 400,
}

# Energy consumption per dollar spent (kWh/$)
# These are rough estimates based on CCF methodology
# Different services have different energy profiles
SERVICE_ENERGY_FACTORS = {
    "Amazon Elastic Compute Cloud - Compute": 0.05,  # EC2 is energy-intensive
    "Amazon Simple Storage Service": 0.01,           # S3 is efficient
    "Amazon Relational Database Service": 0.04,      # RDS moderate
    "Amazon CloudFront": 0.02,                       # CDN is efficient
    "AWS Lambda": 0.03,                              # Serverless moderate
    "Amazon DynamoDB": 0.02,                         # NoSQL efficient
    "default": 0.03,                                 # Default estimate
}

# Power Usage Effectiveness (PUE) - datacenter overhead
# AWS reports PUE of ~1.2 for modern datacenters
AWS_PUE = 1.2


class CarbonCalculator:
    """
    Calculates carbon footprint from cloud cost data.
    
    Methodology:
    1. Estimate energy (kWh) from cost using service-specific factors
    2. Apply PUE multiplier for datacenter overhead
    3. Multiply by region carbon intensity (gCO₂/kWh)
    4. Convert to kg CO₂
    """
    
    def calculate_from_costs(
        self,
        cost_data: List[Dict[str, Any]],
        region: str = "us-east-1",
    ) -> Dict[str, Any]:
        """
        Calculate carbon footprint from AWS cost data.
        
        Args:
            cost_data: Cost records from AWS Cost Explorer
            region: AWS region (for carbon intensity lookup)
        
        Returns:
            Dict with total emissions, breakdown, and equivalencies
        """
        total_cost_usd = Decimal("0")
        total_energy_kwh = Decimal("0")
        
        # Sum up costs and estimate energy
        for record in cost_data:
            try:
                cost_amount = Decimal(
                    record.get("Total", {})
                    .get("UnblendedCost", {})
                    .get("Amount", "0")
                )
                # Only count positive costs
                if cost_amount > 0:
                    total_cost_usd += cost_amount
                    # Estimate energy using default factor
                    energy_factor = Decimal(str(SERVICE_ENERGY_FACTORS["default"]))
                    total_energy_kwh += cost_amount * energy_factor
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("carbon_calc_skip_record", error=str(e))
                continue
        
        # Apply PUE (datacenter overhead)
        total_energy_with_pue = total_energy_kwh * Decimal(str(AWS_PUE))
        
        # Get carbon intensity for region
        carbon_intensity = REGION_CARBON_INTENSITY.get(
            region, REGION_CARBON_INTENSITY["default"]
        )
        
        # Calculate CO₂ in grams
        co2_grams = total_energy_with_pue * Decimal(str(carbon_intensity))
        
        # Convert to kg
        co2_kg = co2_grams / Decimal("1000")
        
        # Calculate equivalencies for user-friendly display
        equivalencies = self._calculate_equivalencies(float(co2_kg))
        
        result = {
            "total_co2_kg": round(float(co2_kg), 3),
            "total_cost_usd": round(float(total_cost_usd), 2),
            "estimated_energy_kwh": round(float(total_energy_with_pue), 3),
            "region": region,
            "carbon_intensity_gco2_kwh": carbon_intensity,
            "equivalencies": equivalencies,
            "methodology": "Based on Cloud Carbon Footprint methodology",
        }
        
        logger.info(
            "carbon_calculated",
            co2_kg=result["total_co2_kg"],
            cost_usd=result["total_cost_usd"],
            region=region,
        )
        
        return result
    
    def _calculate_equivalencies(self, co2_kg: float) -> Dict[str, Any]:
        """
        Convert CO₂ to relatable equivalencies.
        
        Sources: EPA Greenhouse Gas Equivalencies Calculator
        """
        return {
            # Average car emits 404g CO₂ per mile
            "miles_driven": round(co2_kg * 1000 / 404, 1),
            
            # One tree absorbs ~22kg CO₂ per year
            "trees_needed_for_year": round(co2_kg / 22, 1),
            
            # Average smartphone charge uses ~0.0085 kWh = ~3.4g CO₂
            "smartphone_charges": round(co2_kg * 1000 / 3.4, 0),
            
            # Average home uses ~900kWh/month = ~360kg CO₂/month
            "percent_of_home_month": round((co2_kg / 360) * 100, 2),
        }