const DRAFT_ID_KEY = "intake_consult_draft_id";
const CLIENT_ID_KEY = "intake_consult_client_id";
const BUSINESS_NAME_KEY = "intake_consult_business_name";
const ADDRESS_KEY = "intake_consult_address";
const ADDRESS_STREET_KEY = "intake_consult_address_street";
const ADDRESS_CITY_KEY = "intake_consult_address_city";
const ADDRESS_STATE_KEY = "intake_consult_address_state";
const ADDRESS_ZIP_KEY = "intake_consult_address_zip";
const ADDRESS_COUNTRY_KEY = "intake_consult_address_country";
const BUSINESS_START_DATE_KEY = "intake_consult_business_start_date";

export const consultStorage = {
  getDraftId: () => sessionStorage.getItem(DRAFT_ID_KEY),
  getClientId: () => sessionStorage.getItem(CLIENT_ID_KEY),
  getBusinessName: () => sessionStorage.getItem(BUSINESS_NAME_KEY),
  getAddress: () => sessionStorage.getItem(ADDRESS_KEY),
  getAddressStreet: () => sessionStorage.getItem(ADDRESS_STREET_KEY),
  getAddressCity: () => sessionStorage.getItem(ADDRESS_CITY_KEY),
  getAddressState: () => sessionStorage.getItem(ADDRESS_STATE_KEY),
  getAddressZip: () => sessionStorage.getItem(ADDRESS_ZIP_KEY),
  getAddressCountry: () => sessionStorage.getItem(ADDRESS_COUNTRY_KEY),
  getBusinessStartDate: () => sessionStorage.getItem(BUSINESS_START_DATE_KEY),
  set: (draft_id: string, client_id: string) => {
    sessionStorage.setItem(DRAFT_ID_KEY, draft_id);
    sessionStorage.setItem(CLIENT_ID_KEY, client_id);
  },
  setBusinessName: (value: string) => {
    sessionStorage.setItem(BUSINESS_NAME_KEY, value);
  },
  setAddress: (value: string) => {
    sessionStorage.setItem(ADDRESS_KEY, value);
  },
  setAddressParts: (parts: {
    street: string;
    city: string;
    state: string;
    zip: string;
    country: string;
  }) => {
    sessionStorage.setItem(ADDRESS_STREET_KEY, parts.street);
    sessionStorage.setItem(ADDRESS_CITY_KEY, parts.city);
    sessionStorage.setItem(ADDRESS_STATE_KEY, parts.state);
    sessionStorage.setItem(ADDRESS_ZIP_KEY, parts.zip);
    sessionStorage.setItem(ADDRESS_COUNTRY_KEY, parts.country);
  },
  setBusinessStartDate: (value: string) => {
    sessionStorage.setItem(BUSINESS_START_DATE_KEY, value);
  },
  clear: () => {
    sessionStorage.removeItem(DRAFT_ID_KEY);
    sessionStorage.removeItem(CLIENT_ID_KEY);
    sessionStorage.removeItem(BUSINESS_NAME_KEY);
    sessionStorage.removeItem(ADDRESS_KEY);
    sessionStorage.removeItem(ADDRESS_STREET_KEY);
    sessionStorage.removeItem(ADDRESS_CITY_KEY);
    sessionStorage.removeItem(ADDRESS_STATE_KEY);
    sessionStorage.removeItem(ADDRESS_ZIP_KEY);
    sessionStorage.removeItem(ADDRESS_COUNTRY_KEY);
    sessionStorage.removeItem(BUSINESS_START_DATE_KEY);
  },
};
