import logging

logger = logging.getLogger(__name__)

# Simulating a database or external source
# In production, this would be fetched from a database where admins can update it.
# Comprehensive list of schemes focused on Jharkhand farmers
MOCK_SCHEMES_DATA = [
    {
        "name": "Jharkhand Rajya Fasal Rahat Yojana (JRFRY)",
        "benefit": "Financial assistance in case of crop loss due to natural calamities without any premium payment.",
        "eligibility": "All landholding and landless farmers in Jharkhand.",
        "link": "https://jrfry.jharkhand.gov.in/",
    },
    {
        "name": "Jharkhand Krishi Rin Mafi Yojana",
        "benefit": "Waiver of short-term agricultural loans up to ₹2,00,000 for relief from debt burden.",
        "eligibility": "Standard crop loan account holders (KCC) in Jharkhand.",
        "link": "https://jkrmy.jharkhand.gov.in/",
    },
    {
        "name": "Kisan Samriddhi Yojana (Jharkhand)",
        "benefit": "Up to 90% subsidy on solar-powered irrigation units for sustainable agriculture.",
        "eligibility": "Farmers of Jharkhand aiming to adopt solar irrigation.",
        "link": "https://www.myscheme.gov.in/",
    },
    {
        "name": "Mukhyamantri Krishi Ashirwad Yojana",
        "benefit": "₹5,000 per acre (up to 5 acres) per year as direct benefit transfer to boost agricultural investment.",
        "eligibility": "Small and marginal farmers of Jharkhand holding up to 5 acres.",
        "link": "https://mmkay.jharkhand.gov.in/",
    },
    {
        "name": "Micro Irrigation Scheme (PMKSY - Jharkhand)",
        "benefit": "Provides up to 90% financial assistance for drip and sprinkler irrigation systems.",
        "eligibility": "Farmers in Jharkhand seeking to enhance water use efficiency.",
        "link": "http://jharkhandpdmc.com/",
    },
    {
        "name": "PM-KISAN",
        "benefit": "₹6,000 per year direct income support in three equal instalments.",
        "eligibility": "All landholding farmer families with cultivable land records across India, including Jharkhand.",
        "link": "https://pmkisan.gov.in",
    }
]

async def get_all_schemes():
    """
    Returns the list of all available agriculture schemes.
    """
    logger.info("Fetching schemes data")
    return MOCK_SCHEMES_DATA
