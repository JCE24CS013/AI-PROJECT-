from django.core.management.base import BaseCommand
from core.food_data import REGIONAL_DISH_SUGGESTIONS
from core.models import Destination, RegionalDishSuggestion


INDIA_DESTINATIONS = [
    ("Tirumala Venkateswara Temple", "culture", "Andhra Pradesh", "Major pilgrimage temple in the Tirumala hills.", 13.6833, 79.3472, "culture|pilgrimage"),
    ("Araku Valley", "nature", "Andhra Pradesh", "Eastern Ghats valley known for mountain scenery and coffee-growing country.", 18.3273, 82.8775, "nature|coffee|hills"),
    ("Borra Caves", "adventure", "Andhra Pradesh", "Limestone cave system in the Ananthagiri hills; check access before travel.", 18.2801, 83.0397, "adventure|nature|caves"),
    ("Tawang Monastery", "culture", "Arunachal Pradesh", "Historic Buddhist monastery in the Tawang region.", 27.5861, 91.8594, "culture|history|monastery"),
    ("Sela Pass", "nature", "Arunachal Pradesh", "High mountain pass connecting areas around Tawang; weather can affect access.", 27.5058, 92.1024, "nature|adventure|mountains"),
    ("Ziro Valley", "nature", "Arunachal Pradesh", "Highland valley with villages and landscapes of the Apatani plateau.", 27.5448, 93.8197, "nature|culture|valley"),
    ("Kaziranga National Park", "nature", "Assam", "Protected grassland and wetland landscape; safari access is seasonal and regulated.", 26.5775, 93.1711, "nature|wildlife"),
    ("Kamakhya Temple", "culture", "Assam", "Historic hilltop temple in Guwahati.", 26.1664, 91.7051, "culture|history|pilgrimage"),
    ("Majuli Island", "culture", "Assam", "Brahmaputra river island noted for Vaishnavite satras and river landscapes.", 26.9525, 94.1737, "culture|nature|river"),
    ("Mahabodhi Temple", "history", "Bihar", "UNESCO-listed Buddhist temple complex at Bodh Gaya.", 24.6959, 84.9913, "history|culture|pilgrimage"),
    ("Nalanda Mahavihara", "history", "Bihar", "Archaeological remains of the historic Nalanda learning centre.", 25.1357, 85.4430, "history|culture"),
    ("Takht Sri Patna Sahib", "culture", "Bihar", "Important Sikh gurdwara in Patna.", 25.6208, 85.1811, "culture|history|pilgrimage"),
    ("Chitrakote Falls", "nature", "Chhattisgarh", "Broad waterfall on the Indravati River; flow varies by season.", 19.2006, 81.7004, "nature|waterfall"),
    ("Kanger Valley National Park", "nature", "Chhattisgarh", "Protected forest area with caves and waterfalls; confirm access locally.", 18.8510, 81.9360, "nature|wildlife|caves"),
    ("Sirpur Archaeological Site", "history", "Chhattisgarh", "Historic temple and monastic remains near the Mahanadi.", 21.3392, 82.1910, "history|culture|archaeology"),
    ("Basilica of Bom Jesus", "history", "Goa", "Historic church in Old Goa, part of the Churches and Convents of Goa UNESCO site.", 15.5009, 73.9114, "history|culture|architecture"),
    ("Calangute Beach", "beach", "Goa", "Popular North Goa beach; swimming and sea conditions vary.", 15.5440, 73.7550, "beach|coast"),
    ("Dudhsagar Falls", "nature", "Goa", "Seasonal waterfall in the Western Ghats; access rules and transport vary.", 15.3144, 74.3143, "nature|waterfall|adventure"),
    ("Statue of Unity", "culture", "Gujarat", "Large memorial statue and visitor complex near the Narmada River.", 21.8380, 73.7191, "culture|architecture"),
    ("Somnath Temple", "culture", "Gujarat", "Coastal temple and pilgrimage site on the Saurashtra coast.", 20.8880, 70.4012, "culture|history|pilgrimage"),
    ("Great Rann of Kutch", "nature", "Gujarat", "Seasonal salt-marsh landscape; access and viewing conditions vary.", 23.8360, 69.8580, "nature|desert|culture"),
    ("Brahma Sarovar", "culture", "Haryana", "Sacred water tank and pilgrimage area in Kurukshetra.", 29.9695, 76.8443, "culture|history|pilgrimage"),
    ("Sultanpur National Park", "nature", "Haryana", "Wetland bird sanctuary near Gurugram; check seasonal opening details.", 28.4610, 76.8920, "nature|wildlife|birds"),
    ("Yadavindra Gardens", "culture", "Haryana", "Historic terraced garden complex at Pinjore.", 30.7980, 76.9180, "culture|history|gardens"),
    ("Ridge, Shimla", "nature", "Himachal Pradesh", "Central open promenade in Shimla with views toward the surrounding hills.", 31.1048, 77.1734, "nature|culture|hills"),
    ("Hadimba Devi Temple", "culture", "Himachal Pradesh", "Wooden temple in Manali set among cedar forest.", 32.2432, 77.1892, "culture|nature|architecture"),
    ("Bhagsunag Waterfall", "nature", "Himachal Pradesh", "Waterfall and walking area near McLeod Ganj; flow varies by season.", 32.2426, 76.3200, "nature|waterfall|hiking"),
    ("Baidyanath Temple", "culture", "Jharkhand", "Major temple complex in Deoghar.", 24.4921, 86.6980, "culture|history|pilgrimage"),
    ("Betla National Park", "nature", "Jharkhand", "Protected forest and wildlife area on the Chota Nagpur Plateau; check park access.", 23.8870, 84.1900, "nature|wildlife"),
    ("Hundru Falls", "nature", "Jharkhand", "Waterfall on the Subarnarekha River near Ranchi.", 23.4440, 85.6610, "nature|waterfall"),
    ("Hampi Group of Monuments", "history", "Karnataka", "UNESCO-listed Vijayanagara-era archaeological landscape.", 15.3350, 76.4600, "history|culture|architecture"),
    ("Mysore Palace", "history", "Karnataka", "Historic royal palace in Mysuru; check current visitor hours.", 12.3052, 76.6552, "history|culture|architecture"),
    ("Abbey Falls", "nature", "Karnataka", "Waterfall near Madikeri in the Coorg region; flow is seasonal.", 12.4580, 75.7380, "nature|waterfall"),
    ("Alappuzha Backwaters", "nature", "Kerala", "Backwater landscape and waterways around Alappuzha; boat operators set schedules.", 9.4981, 76.3388, "nature|water|culture"),
    ("Thekkady and Periyar", "nature", "Kerala", "Forest and lake area around Periyar Tiger Reserve; activities are regulated.", 9.6031, 77.1610, "nature|wildlife"),
    ("Edakkal Caves", "history", "Kerala", "Rock shelter with prehistoric carvings in Wayanad; access involves a climb.", 11.6050, 76.2350, "history|nature|archaeology"),
    ("Kovalam Beach", "beach", "Kerala", "Coastal beach area south of Thiruvananthapuram; sea conditions vary.", 8.4004, 76.9784, "beach|coast"),
    ("Athirappilly Falls", "nature", "Kerala", "Waterfall on the Chalakudy River; flow changes with season.", 10.2850, 76.5690, "nature|waterfall"),
    ("Khajuraho Group of Monuments", "history", "Madhya Pradesh", "UNESCO-listed temple group known for medieval architecture and sculpture.", 24.8520, 79.9190, "history|culture|architecture"),
    ("Sanchi Stupa", "history", "Madhya Pradesh", "UNESCO-listed Buddhist monuments and stupas.", 23.4793, 77.7397, "history|culture|archaeology"),
    ("Kanha National Park", "nature", "Madhya Pradesh", "Protected forest and wildlife reserve; safari permits are limited.", 22.3345, 80.6115, "nature|wildlife"),
    ("Gateway of India", "history", "Maharashtra", "Waterfront monument in Mumbai overlooking the Arabian Sea.", 18.9220, 72.8347, "history|culture|architecture"),
    ("Ajanta Caves", "history", "Maharashtra", "UNESCO-listed Buddhist cave monuments with historic paintings and sculpture.", 20.5519, 75.7033, "history|culture|archaeology"),
    ("Shivneri Fort", "history", "Maharashtra", "Hill fort near Junnar; access includes a steep approach.", 19.1980, 73.8750, "history|adventure|fort"),
    ("Loktak Lake", "nature", "Manipur", "Freshwater lake known for floating phumdis; local boat access varies.", 24.5500, 93.7800, "nature|lake|culture"),
    ("Kangla Fort", "history", "Manipur", "Historic fort and heritage area in Imphal.", 24.7990, 93.9390, "history|culture"),
    ("Shirui Hills", "nature", "Manipur", "Highland area near Ukhrul; seasonal flowers and access should be checked locally.", 25.1200, 94.3600, "nature|hills|flowers"),
    ("Umiam Lake", "nature", "Meghalaya", "Reservoir and viewpoint area north of Shillong.", 25.6670, 91.9000, "nature|lake"),
    ("Nohkalikai Falls", "nature", "Meghalaya", "High waterfall viewpoint near Cherrapunji; visibility depends on weather.", 25.2700, 91.6900, "nature|waterfall"),
    ("Dawki and Umngot River", "nature", "Meghalaya", "River and border-region scenery near Dawki; water clarity varies by season.", 25.1900, 92.0200, "nature|river|adventure"),
    ("Vantawng Falls", "nature", "Mizoram", "Tall waterfall in Serchhip district; viewing access is from designated areas.", 23.2780, 92.6600, "nature|waterfall"),
    ("Reiek Tlang", "nature", "Mizoram", "Hill and village heritage area near Aizawl.", 23.6800, 92.5800, "nature|culture|hills"),
    ("Solomon's Temple", "culture", "Mizoram", "Large church complex and landmark in Aizawl.", 23.7270, 92.7240, "culture|architecture"),
    ("Kohima War Cemetery", "history", "Nagaland", "Commonwealth war cemetery commemorating the Battle of Kohima.", 25.6740, 94.1080, "history|memorial"),
    ("Dzukou Valley", "nature", "Nagaland", "High-altitude valley and trekking area; conditions and access require local checks.", 25.5700, 94.1300, "nature|adventure|hiking"),
    ("Khonoma Village", "culture", "Nagaland", "Angami village known for community conservation and cultural heritage.", 25.6600, 94.0100, "culture|nature|village"),
    ("Konark Sun Temple", "history", "Odisha", "UNESCO-listed 13th-century temple on the Bay of Bengal coast.", 19.8876, 86.0945, "history|culture|architecture"),
    ("Jagannath Temple, Puri", "culture", "Odisha", "Major pilgrimage temple; access restrictions apply to some visitors.", 19.8048, 85.8170, "culture|pilgrimage"),
    ("Chilika Lake", "nature", "Odisha", "Large coastal lagoon and bird habitat; boat trips and sightings are seasonal.", 19.7000, 85.3200, "nature|lake|birds"),
    ("Golden Temple", "culture", "Punjab", "Harmandir Sahib complex in Amritsar; visitors should follow site etiquette.", 31.6200, 74.8765, "culture|history|pilgrimage"),
    ("Jallianwala Bagh", "history", "Punjab", "Memorial garden in Amritsar commemorating the 1919 massacre.", 31.6200, 74.8800, "history|memorial"),
    ("Virasat-e-Khalsa", "culture", "Punjab", "Museum of Sikh history and heritage in Anandpur Sahib.", 31.2350, 76.5020, "culture|history|museum"),
    ("Amber Fort", "history", "Rajasthan", "Hilltop fort and palace complex near Jaipur.", 26.9855, 75.8513, "history|culture|fort"),
    ("City Palace, Udaipur", "history", "Rajasthan", "Historic palace complex beside Lake Pichola.", 24.5764, 73.6835, "history|culture|architecture"),
    ("Jaisalmer Fort", "history", "Rajasthan", "Historic living fort in the Thar Desert city of Jaisalmer.", 26.9124, 70.9120, "history|culture|fort"),
    ("Rumtek Monastery", "culture", "Sikkim", "Tibetan Buddhist monastery near Gangtok.", 27.3090, 88.5620, "culture|history|monastery"),
    ("Tsomgo Lake", "nature", "Sikkim", "High-altitude glacial lake; permits and weather-dependent access apply.", 27.3740, 88.7630, "nature|lake|mountains"),
    ("Pemayangtse Monastery", "culture", "Sikkim", "Historic Buddhist monastery near Pelling.", 27.3050, 88.2500, "culture|history|monastery"),
    ("Meenakshi Amman Temple", "culture", "Tamil Nadu", "Historic temple complex in Madurai.", 9.9195, 78.1193, "culture|history|architecture"),
    ("Ooty Botanical Gardens", "nature", "Tamil Nadu", "Botanical garden in the Nilgiri hill station of Ooty.", 11.4120, 76.6910, "nature|gardens|hills"),
    ("Shore Temple, Mahabalipuram", "history", "Tamil Nadu", "UNESCO-listed Pallava-era coastal temple.", 12.6160, 80.1990, "history|culture|architecture"),
    ("Charminar", "history", "Telangana", "Historic monument and landmark in Hyderabad's old city.", 17.3616, 78.4747, "history|culture|architecture"),
    ("Ramappa Temple", "history", "Telangana", "UNESCO-listed Kakatiya temple near Palampet.", 18.2590, 79.9430, "history|culture|architecture"),
    ("Bhadrachalam Temple", "culture", "Telangana", "Riverside temple and pilgrimage site on the Godavari.", 17.6680, 80.8880, "culture|pilgrimage"),
    ("Ujjayanta Palace", "history", "Tripura", "Former royal palace in Agartala, now a museum.", 23.8360, 91.2790, "history|culture|museum"),
    ("Neermahal", "history", "Tripura", "Lake palace on Rudrasagar Lake; boat schedules vary.", 23.4970, 91.3090, "history|culture|lake"),
    ("Unakoti", "history", "Tripura", "Rock-cut Shaivite sculptures and archaeological site.", 24.3230, 92.0700, "history|culture|archaeology"),
    ("Taj Mahal", "history", "Uttar Pradesh", "UNESCO-listed Mughal mausoleum in Agra; check current entry arrangements.", 27.1751, 78.0421, "history|culture|architecture"),
    ("Dashashwamedh Ghat", "culture", "Uttar Pradesh", "Historic riverfront ghat in Varanasi; ceremonies and river conditions vary.", 25.3060, 83.0100, "culture|history|river"),
    ("Bara Imambara", "history", "Uttar Pradesh", "Historic complex in Lucknow known for its central hall and courtyards.", 26.8690, 80.9120, "history|culture|architecture"),
    ("Naini Lake", "nature", "Uttarakhand", "Lake and promenade in Nainital; boating depends on local conditions.", 29.3910, 79.4540, "nature|lake|hills"),
    ("Kedarnath Temple", "culture", "Uttarakhand", "High-altitude Himalayan pilgrimage destination with seasonal access.", 30.7346, 79.0669, "culture|pilgrimage|mountains"),
    ("Valley of Flowers National Park", "nature", "Uttarakhand", "UNESCO-listed alpine valley; open seasonally and reached by a trek.", 30.7280, 79.6050, "nature|hiking|flowers"),
    ("Victoria Memorial", "history", "West Bengal", "Museum and memorial building in Kolkata.", 22.5448, 88.3426, "history|culture|museum"),
    ("Darjeeling Himalayan Railway", "culture", "West Bengal", "UNESCO-listed mountain railway; service and timetables vary.", 27.0410, 88.2663, "culture|history|mountains"),
    ("Sundarbans National Park", "nature", "West Bengal", "Mangrove forest and tiger reserve; permits and guided access are required.", 21.9497, 88.8890, "nature|wildlife|mangrove"),
    ("Cellular Jail", "history", "Andaman and Nicobar Islands", "Former colonial prison and national memorial in Port Blair.", 11.6700, 92.7500, "history|memorial"),
    ("Radhanagar Beach", "beach", "Andaman and Nicobar Islands", "Coastal beach on Swaraj Dweep; swimming conditions vary.", 12.0060, 92.9640, "beach|coast"),
    ("Netaji Subhas Chandra Bose Island", "history", "Andaman and Nicobar Islands", "Historic island destination near Port Blair; ferry access is required.", 11.6750, 92.7620, "history|nature"),
    ("Rock Garden, Chandigarh", "culture", "Chandigarh", "Sculpture garden built from reused materials.", 30.7525, 76.8095, "culture|art|gardens"),
    ("Sukhna Lake", "nature", "Chandigarh", "Reservoir and public promenade at the edge of Chandigarh.", 30.7420, 76.8180, "nature|lake"),
    ("Capitol Complex, Chandigarh", "history", "Chandigarh", "UNESCO-listed modernist government complex; check visitor access requirements.", 30.7600, 76.8070, "history|architecture"),
    ("Vanganga Lake Garden", "nature", "Dadra and Nagar Haveli and Daman and Diu", "Garden and lake area in Silvassa.", 20.2730, 73.0100, "nature|gardens|lake"),
    ("Dudhni Lake", "nature", "Dadra and Nagar Haveli and Daman and Diu", "Reservoir landscape near Silvassa; activities depend on local operators.", 20.2200, 73.0900, "nature|lake"),
    ("Diu Fort", "history", "Dadra and Nagar Haveli and Daman and Diu", "Portuguese-era coastal fort on Diu island.", 20.7150, 70.9870, "history|culture|fort"),
    ("Red Fort", "history", "Delhi", "UNESCO-listed Mughal fort complex in Old Delhi.", 28.6562, 77.2410, "history|culture|architecture"),
    ("Humayun's Tomb", "history", "Delhi", "UNESCO-listed Mughal garden-tomb complex in Delhi.", 28.5933, 77.2507, "history|culture|architecture"),
    ("Qutub Minar", "history", "Delhi", "UNESCO-listed minaret and archaeological complex.", 28.5245, 77.1855, "history|culture|architecture"),
    ("Dal Lake", "nature", "Jammu and Kashmir", "Lake and houseboat area in Srinagar; boat services and weather vary.", 34.0837, 74.8760, "nature|lake|culture"),
    ("Gulmarg", "nature", "Jammu and Kashmir", "Mountain resort and meadow area; snow and lift access are seasonal.", 34.0484, 74.3805, "nature|mountains|adventure"),
    ("Vaishno Devi Bhawan", "culture", "Jammu and Kashmir", "Pilgrimage shrine reached by a regulated mountain route.", 33.0300, 74.9500, "culture|pilgrimage|hiking"),
    ("Leh Palace", "history", "Ladakh", "Historic palace overlooking Leh; altitude acclimatization is important.", 34.1650, 77.5850, "history|culture|architecture"),
    ("Pangong Tso", "nature", "Ladakh", "High-altitude lake in a remote border region; permits and conditions apply.", 33.7500, 78.6700, "nature|lake|mountains"),
    ("Diskit Monastery", "culture", "Ladakh", "Buddhist monastery in Nubra Valley.", 34.5530, 77.5460, "culture|history|monastery"),
    ("Agatti Island", "beach", "Lakshadweep", "Coral island; entry permits and transport must be arranged in advance.", 10.8500, 72.1900, "beach|island|nature"),
    ("Kavaratti Island", "beach", "Lakshadweep", "Island capital with lagoon scenery; access is regulated.", 10.5667, 72.6420, "beach|island|nature"),
    ("Bangaram Island", "beach", "Lakshadweep", "Small coral island; access and stay arrangements require advance confirmation.", 10.9400, 72.2900, "beach|island|nature"),
    ("Promenade Beach", "beach", "Puducherry", "Seafront promenade in Puducherry's heritage quarter.", 11.9320, 79.8350, "beach|culture|coast"),
    ("Auroville", "culture", "Puducherry", "International township near Puducherry; visitor access varies by area.", 12.0050, 79.8100, "culture|architecture"),
    ("Paradise Beach", "beach", "Puducherry", "Beach reached by boat from the Chunnambar area; services are weather-dependent.", 11.9120, 79.8120, "beach|coast"),
]


class Command(BaseCommand):
    help = "Seed sample destinations and a curated India-wide tourist destination catalog"

    def handle(self, *args, **options):
        Destination.objects.get_or_create(
            name="Fort Kochi",
            defaults={
                "category": "culture",
                "region": "Kochi",
                "description": "Historic waterfront with colonial heritage and cafes.",
                "latitude": 9.9659,
                "longitude": 76.2413,
                "best_for": "culture|history",
                "visit_hours": "9:00 AM - 8:00 PM",
            },
        )
        Destination.objects.get_or_create(
            name="Munnar",
            defaults={
                "category": "nature",
                "region": "Kerala",
                "description": "Tea gardens and scenic mountain views.",
                "latitude": 10.0889,
                "longitude": 77.0595,
                "best_for": "nature|adventure",
                "visit_hours": "8:00 AM - 5:00 PM",
            },
        )
        Destination.objects.get_or_create(
            name="Vypin Beach",
            defaults={
                "category": "beach",
                "region": "Kochi",
                "description": "A broad sandy coast with calm waters and sunset views.",
                "latitude": 10.0544,
                "longitude": 76.1707,
                "best_for": "beach|relaxation",
                "visit_hours": "6:00 AM - 7:00 PM",
            },
        )

        created_count = 0
        for name, category, region, description, latitude, longitude, best_for in INDIA_DESTINATIONS:
            _, created = Destination.objects.get_or_create(
                name=name,
                defaults={
                    "category": category,
                    "region": region,
                    "description": description,
                    "latitude": latitude,
                    "longitude": longitude,
                    "best_for": best_for,
                },
            )
            created_count += created

        dish_count = 0
        for region, dishes in REGIONAL_DISH_SUGGESTIONS.items():
            for name, description in dishes:
                _, created = RegionalDishSuggestion.objects.get_or_create(
                    region=region,
                    name=name,
                    defaults={"description": description},
                )
                dish_count += created

        self.stdout.write(
            self.style.SUCCESS(
                f"India destination catalog ready: {len(INDIA_DESTINATIONS)} curated places "
                f"({created_count} newly added), plus {dish_count} new regional dish suggestions. "
                "Existing destinations and restaurant data were preserved."
            )
        )
