"""
DHM station configuration for the fetch_dhm_discharge management command.

Each key is a human-readable station name.  Each value is a dict with:
  seriesid   – DHM River Watch series ID used in the POST request
  station_id – The station_id field on the DischargeStation model in this
               Django project.  Set this to match the value stored in your
               database.  Leave as an empty string ("") for stations that
               have no corresponding DischargeStation record yet; those
               stations will be fetched but NOT written to the database
               until a station_id is provided.

HOW TO LINK A STATION
---------------------
1. In the Django admin (or shell) find the station_id of the DischargeStation
   you want to link, e.g. "LIKHU_001".
2. Update the corresponding entry below:
       "station_id": "LIKHU_001"
3. Rerun the command — data will now be persisted.
"""

DHM_STATIONS = {
    "Likhu_Sangutar": {
        "seriesid": "3004",
        "station_id": "1",          # lower likhu (DB station_id=1)
    },
    "Trishuli_Betrawati": {
        "seriesid": "943",
        "station_id": "",
    },
    "Mewa_Taplejung": {
        "seriesid": "3291",
        "station_id": "",
    },
    "MaiKhola_Chisapani": {
        "seriesid": "19622",
        "station_id": "",
    },
    "TamorRiver_Majhitar": {
        "seriesid": "3333",
        "station_id": "",
    },
    "Lohandra_Khola_Shisbeni": {
        "seriesid": "27681",
        "station_id": "",
    },
    "Arun_River_Uwa_Gau": {
        "seriesid": "2874",
        "station_id": "",
    },
    "BarunRiver_Syaksila": {
        "seriesid": "21089",
        "station_id": "",
    },
    "Hinwa_Khola_Pipletar": {
        "seriesid": "2916",
        "station_id": "",
    },
    "Sabhaya_Khola_Tumlingtar": {
        "seriesid": "2895",
        "station_id": "",
    },
    "Arun_Turkeghat": {
        "seriesid": "1481",
        "station_id": "",
    },
    "Sardu_Khola_MadanBhandariHighway": {
        "seriesid": "27871",
        "station_id": "",
    },
    "Seuti_Khola_Bihibare_Bazar": {
        "seriesid": "27879",
        "station_id": "",
    },
    "Triyuga_Khola_Gaighat": {
        "seriesid": "27211",
        "station_id": "",
    },
    "Dudh_Koshi_Rabuwabazar": {
        "seriesid": "1500",
        "station_id": "",
    },
    "Tawa_bridge_Us_Tawakhola": {
        "seriesid": "27548",
        "station_id": "",
    },
    "Solu_Khola_Salme": {
        "seriesid": "3144",
        "station_id": "",
    },
    "Rolwaling_River_Beding": {
        "seriesid": "30890",
        "station_id": "",
    },
    "KhimtiKhola_Rasnalu": {
        "seriesid": "19657",
        "station_id": "",
    },
    "Chadaha_Khola_Belghari": {
        "seriesid": "27850",
        "station_id": "",
    },
    "Driga_Khola_Tinpatan_Bridge": {
        "seriesid": "27834",
        "station_id": "",
    },
    "Ratu_River_Lalghad": {
        "seriesid": "26081",
        "station_id": "",
    },
    "Ratu_River_BP_Highway": {
        "seriesid": "26090",
        "station_id": "",
    },
    "Kamala_River_Mai_sthan": {
        "seriesid": "26070",
        "station_id": "",
    },
    "Sunkoshi_Khurkot": {
        "seriesid": "3754",
        "station_id": "",
    },
    "Bhote_Koshi_Bahrabise": {
        "seriesid": "1640",
        "station_id": "",
    },
    "Balefi_Jalbire": {
        "seriesid": "32",
        "station_id": "",
    },
    "Sunkoshi_Pachuwarghat": {
        "seriesid": "1453",
        "station_id": "",
    },
    "Kokhajor_Khola_Hariharpur_Gadi": {
        "seriesid": "2832",
        "station_id": "",
    },
    "Chandi_Khola_Chapur": {
        "seriesid": "26146",
        "station_id": "",
    },
    "Rosi_Khola_Panauti": {
        "seriesid": "1120",
        "station_id": "",
    },
    "Melamchi_Nakote": {
        "seriesid": "445",
        "station_id": "",
    },
    "Nagmati_River_Sundarijal": {
        "seriesid": "21597",
        "station_id": "",
    },
    "Bagmati_River_Sundarijal": {
        "seriesid": "3400",
        "station_id": "",
    },
    "Salinadi_Sankhu_Telemetry": {
        "seriesid": "26297",
        "station_id": "",
    },
    "Lal_Bakiya_Khola_Jureli_Bazar": {
        "seriesid": "26108",
        "station_id": "",
    },
    "Khodku_Khola_Jharuwarasi": {
        "seriesid": "25860",
        "station_id": "",
    },
    "Godawari_Khola_Thaiba": {
        "seriesid": "25902",
        "station_id": "",
    },
    "Hanumante_Khola_Kausaltar": {
        "seriesid": "25911",
        "station_id": "",
    },
    "Manohara_Khola_Balkumari": {
        "seriesid": "4208",
        "station_id": "",
    },
    "Dhobi_Khola_Chabahil": {
        "seriesid": "25842",
        "station_id": "",
    },
    "Dhobi_Khola_Kapan": {
        "seriesid": "25833",
        "station_id": "",
    },
    "Bagmati_River_Sundarijal_Bridge": {
        "seriesid": "4190",
        "station_id": "",
    },
    "Langtang_Khola_Ghodatalbela": {
        "seriesid": "30281",
        "station_id": "",
    },
    "Bhotekoshi_Rasuwagadi": {
        "seriesid": "23251",
        "station_id": "",
    },
    "Nakkhu_Bungmati": {
        "seriesid": "4172",
        "station_id": "",
    },
    "Bagmati_River_Khokana": {
        "seriesid": "927",
        "station_id": "",
    },
    "Bishnumati_Khola_Gongabu_Buspark": {
        "seriesid": "4181",
        "station_id": "",
    },
    "Balkhu_Khola_Balambu": {
        "seriesid": "25851",
        "station_id": "",
    },
    "East_Rapti_at_Rajaiya": {
        "seriesid": "3733",
        "station_id": "",
    },
    "Tadi_Belkot": {
        "seriesid": "1082",
        "station_id": "",
    },
    "Budhi_Gandaki_Aarughat": {
        "seriesid": "3572",
        "station_id": "",
    },
    "Ankhu_Khola_Ankhu_Bagar": {
        "seriesid": "3378",
        "station_id": "",
    },
    "Trishuli_Furke_Khola_Malekhu": {
        "seriesid": "31967",
        "station_id": "",
    },
    "Manahari_Khola_Manahari": {
        "seriesid": "21323",
        "station_id": "",
    },
    "Lothar_Khola_Lothar": {
        "seriesid": "1318",
        "station_id": "",
    },
    "Trishuli_River_Kali_Khola": {
        "seriesid": "19583",
        "station_id": "",
    },
    "Narayani_Devghat": {
        "seriesid": "4140",
        "station_id": "",
    },
    "Daraudi_Khola_Naya_Sangu": {
        "seriesid": "3508",
        "station_id": "",
    },
    "Marsyangdi_Bimalnagar": {
        "seriesid": "2491",
        "station_id": "",
    },
    "Kali_Gandaki_Kota_Gaon": {
        "seriesid": "3677",
        "station_id": "",
    },
    "Seti_Gandaki_Damauli": {
        "seriesid": "19954",
        "station_id": "",
    },
    "Dordi_Khola_Ambote_Bazar": {
        "seriesid": "19984",
        "station_id": "",
    },
    "Khudi_Khola_Khudibazar": {
        "seriesid": "19615",
        "station_id": "",
    },
    "Marsyangdi_Dharapani": {
        "seriesid": "30742",
        "station_id": "",
    },
    "Mardi_Khola_Lahachowk": {
        "seriesid": "2683",
        "station_id": "",
    },
    "Jyagdi_Khola_Dangsing": {
        "seriesid": "19742",
        "station_id": "",
    },
    "Kaligandaki_Kumalgaon": {
        "seriesid": "1468",
        "station_id": "",
    },
    "Kothi_River_Lavani": {
        "seriesid": "31173",
        "station_id": "",
    },
    "Tinau_Butwal": {
        "seriesid": "2533",
        "station_id": "",
    },
    "Dumre_Khola_Kalimati": {
        "seriesid": "3068",
        "station_id": "",
    },
    "Kali_Gandaki_Jomsom": {
        "seriesid": "2554",
        "station_id": "",
    },
    "Kali_Gandaki_Tatopani_Ratopani": {
        "seriesid": "2575",
        "station_id": "",
    },
    "Kali_Gandaki_Kalipul_Beni": {
        "seriesid": "20005",
        "station_id": "",
    },
    "Myagdi_Mangalghat": {
        "seriesid": "3466",
        "station_id": "",
    },
    "Rangsing_Khola_Tinkunne": {
        "seriesid": "31154",
        "station_id": "",
    },
    "West_Rapti_Bagasoti": {
        "seriesid": "2470",
        "station_id": "",
    },
    "Daaram_Khola_Wamitaksar": {
        "seriesid": "2641",
        "station_id": "",
    },
    "Babai_Bhada_Bridge": {
        "seriesid": "642",
        "station_id": "",
    },
    "Karnali_Chisapani_Bridge": {
        "seriesid": "4136",
        "station_id": "",
    },
    "Karnali_Chisapani": {
        "seriesid": "691",
        "station_id": "",
    },
    "Mankhola_Belgaun": {
        "seriesid": "3046",
        "station_id": "",
    },
    "Duduwa_River_364": {
        "seriesid": "19260",
        "station_id": "",
    },
    "West_Rapti_River_Raptisonari": {
        "seriesid": "25217",
        "station_id": "",
    },
    "Lungri_River_Khungri_327": {
        "seriesid": "19650",
        "station_id": "",
    },
    "Thuli_Bheri_Trivenighat": {
        "seriesid": "29841",
        "station_id": "",
    },
    "Jagdulla_River_Hurikot": {
        "seriesid": "12382",
        "station_id": "",
    },
    "Nalgad_Raulakhet": {
        "seriesid": "29997",
        "station_id": "",
    },
    "Sano_Bheri_Simlighat": {
        "seriesid": "2267",
        "station_id": "",
    },
    "Chingar_River_Simlekhet_274": {
        "seriesid": "21349",
        "station_id": "",
    },
    "Karai_River_Gumantar": {
        "seriesid": "30622",
        "station_id": "",
    },
    "Nikash_Khola_HS_Latikoili_Surkhet": {
        "seriesid": "22853",
        "station_id": "",
    },
    "Bheri_Samaijighat": {
        "seriesid": "658",
        "station_id": "",
    },
    "Lohare_Khola_Dailekh": {
        "seriesid": "2356",
        "station_id": "",
    },
    "Karnali_Asaraghat": {
        "seriesid": "1331",
        "station_id": "",
    },
    "Humla_Karnali_Lalighat": {
        "seriesid": "2392",
        "station_id": "",
    },
    "Sinja_Khola_Diware": {
        "seriesid": "2436",
        "station_id": "",
    },
    "Tila_Nala_Raralihi_Nagma": {
        "seriesid": "2414",
        "station_id": "",
    },
    "Rara_Daha_Sen": {
        "seriesid": "21356",
        "station_id": "",
    },
    "Mugu_Karnali_Dhain": {
        "seriesid": "2222",
        "station_id": "",
    },
    "Kuwadi_River_Rigin_209": {
        "seriesid": "21379",
        "station_id": "",
    },
    "Humla_Karnali_Bihichhada": {
        "seriesid": "2199",
        "station_id": "",
    },
    "Humla_Karnali_Jaur_Sarkegad": {
        "seriesid": "2178",
        "station_id": "",
    },
    "Humla_Karnali_Simikot": {
        "seriesid": "31927",
        "station_id": "",
    },
    "Kharpu_Khola_HS": {
        "seriesid": "22788",
        "station_id": "",
    },
    "Pathariya_River_Chacharuwa": {
        "seriesid": "25297",
        "station_id": "",
    },
    "Pathariya_River_Simrana": {
        "seriesid": "32105",
        "station_id": "",
    },
    "Kateni_River_Ratanpur": {
        "seriesid": "25288",
        "station_id": "",
    },
    "Ghuruwa_River_Kharetti": {
        "seriesid": "25255",
        "station_id": "",
    },
    "Kandra_River_Pahalmanpur": {
        "seriesid": "19601",
        "station_id": "",
    },
    "Budiganga_Chitreghat": {
        "seriesid": "1248",
        "station_id": "",
    },
    "Budhiganga_River_Kakarsant": {
        "seriesid": "21372",
        "station_id": "",
    },
    "Kailash_River_Achham": {
        "seriesid": "28008",
        "station_id": "",
    },
    "West_Seti_River_Chainpur": {
        "seriesid": "21365",
        "station_id": "",
    },
    "Bauligad_River_Chainpur": {
        "seriesid": "29711",
        "station_id": "",
    },
    "Langur_Khola": {
        "seriesid": "27386",
        "station_id": "",
    },
    "Taru_Gad": {
        "seriesid": "27348",
        "station_id": "",
    },
    "West_Seti_Dipayal": {
        "seriesid": "801",
        "station_id": "",
    },
    "Gandi_Gad_HS_Naulikot": {
        "seriesid": "22814",
        "station_id": "",
    },
    "Doda_Machheli_River_East_West_Highway": {
        "seriesid": "29089",
        "station_id": "",
    },
    "Sihali_River_Arjuni": {
        "seriesid": "25602",
        "station_id": "",
    },
    "Chaudhar_River_Daiji": {
        "seriesid": "25164",
        "station_id": "",
    },
    "Mahakali_Dodhara_Chandani": {
        "seriesid": "25676",
        "station_id": "",
    },
    "Mahakali_Parigaon": {
        "seriesid": "1234",
        "station_id": "",
    },
    "Rupali_Gad_Rupal": {
        "seriesid": "25137",
        "station_id": "",
    },
    "Kakrighat_River_Bhageshori": {
        "seriesid": "25146",
        "station_id": "",
    },
    "Sakayal_Gad_Dadaban": {
        "seriesid": "25246",
        "station_id": "",
    },
    "Seti_River_Gopaghat": {
        "seriesid": "2334",
        "station_id": "",
    },
    "Sailigad_River_Gautada": {
        "seriesid": "28887",
        "station_id": "",
    },
    "Dhungad_River_Bhasme": {
        "seriesid": "29257",
        "station_id": "",
    },
    "Kalanga_Gad_Bagthala_Bajhang": {
        "seriesid": "25306",
        "station_id": "",
    },
    "Surnaya_Gad_Gajur_Gaon": {
        "seriesid": "3656",
        "station_id": "",
    },
    "Chandre_Gad": {
        "seriesid": "27405",
        "station_id": "",
    },
    "Jamadi_Gad": {
        "seriesid": "27424",
        "station_id": "",
    },
    "Chamelia_Karkale_Gaun": {
        "seriesid": "21571",
        "station_id": "",
    },
    "Naugra_Gad": {
        "seriesid": "27443",
        "station_id": "",
    },
}
