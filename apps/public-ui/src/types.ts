export interface PublicPlace {
  name: string;
  city: string;
  countryCode: string;
  countryName: string;
}

export interface PublicCityCenter {
  key: string;
  name: string;
  countryCode: string;
  point: [number, number];
}

export interface PublicCityData {
  version: number;
  attribution: {
    name: string;
    url: string;
  };
  cities: PublicCityCenter[];
}

export interface PublicPhoto {
  id: string;
  src: string;
  thumbnail: string;
  width: number;
  height: number;
}

export interface PublicTrip {
  id: string;
  date: string;
  year: number;
  title: string;
  places: PublicPlace[];
  photos: PublicPhoto[];
}

export interface PublicData {
  version: number;
  generatedAt: string;
  summary: {
    tripDays: number;
    countries: number;
    featuredPhotos: number;
  };
  countries: { code: string; name: string }[];
  trips: PublicTrip[];
}
