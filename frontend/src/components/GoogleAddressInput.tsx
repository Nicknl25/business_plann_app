import React, { useEffect, useRef } from "react";
import { useFormContext } from "react-hook-form";
import { Input } from "./ui/Input";

type GoogleAddressInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  error?: string;
};

const GoogleAddressInput = React.forwardRef<
  HTMLInputElement,
  GoogleAddressInputProps
>((props, forwardedRef) => {
  const { name, id, value, onChange, onBlur, ...rest } = props;
  const { setValue } = useFormContext<any>();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const autocompleteRef = useRef<any>(null);

  const apiKey =
    ((import.meta as any).env &&
      (import.meta as any).env.GOOGLE_PLACES_API_KEY) ||
    ((import.meta as any).env &&
      (import.meta as any).env.VITE_GOOGLE_PLACES_API_KEY);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const initAutocomplete = () => {
      if (!inputRef.current) return;
      const w = window as any;
      if (!w.google || !w.google.maps || !w.google.maps.places) return;
      if (autocompleteRef.current) return;

      const autocomplete = new w.google.maps.places.Autocomplete(
        inputRef.current,
        {
          types: ["address"],
          componentRestrictions: { country: "us" },
          fields: ["address_components", "formatted_address", "geometry"],
        }
      );

      const handlePlaceChanged = () => {
        const place = autocomplete.getPlace();
        if (!place) return;

        const formatted = place.formatted_address || "";
        const components = place.address_components || [];

        const getComponent = (type: string) => {
          const comp = components.find((c: any) => c.types.includes(type));
          return comp ? comp.long_name : "";
        };

        const streetNumber = getComponent("street_number");
        const route = getComponent("route");
        const city =
          getComponent("locality") ||
          getComponent("sublocality") ||
          getComponent("postal_town");
        const county = getComponent("administrative_area_level_2");
        const state = getComponent("administrative_area_level_1");
        const zip = getComponent("postal_code");
        const country = getComponent("country");

        const location = place.geometry && place.geometry.location;
        const lat =
          location && typeof location.lat === "function"
            ? location.lat()
            : undefined;
        const lng =
          location && typeof location.lng === "function"
            ? location.lng()
            : undefined;

        if (name) {
          setValue(name, formatted, {
            shouldValidate: true,
            shouldDirty: true,
          });
        }

        setValue("business_address", formatted);
        setValue(
          "address_street",
          [streetNumber, route].filter(Boolean).join(" ").trim()
        );
        setValue("address_city", city);
        setValue("address_state", state);
        setValue("address_county", county);
        setValue("address_zip", zip);
        setValue("address_country", country);
        if (typeof lat === "number") {
          setValue("address_lat", lat);
        }
        if (typeof lng === "number") {
          setValue("address_lng", lng);
        }

        if (onChange) {
          onChange({
            target: {
              name,
              id,
              value: formatted,
            },
          } as any);
        }
      };

      autocomplete.addListener("place_changed", handlePlaceChanged);
      autocompleteRef.current = autocomplete;
    };

    const w = window as any;

    if (w.google && w.google.maps && w.google.maps.places) {
      initAutocomplete();
      return;
    }

    const existingScript = document.querySelector<HTMLScriptElement>(
      'script[data-google-places="true"]'
    );

    const handleLoaded = () => {
      initAutocomplete();
    };

    if (existingScript) {
      existingScript.addEventListener("load", handleLoaded);
      return () => {
        existingScript.removeEventListener("load", handleLoaded);
      };
    }

    if (!apiKey) {
      console.warn(
        "Google Places API key is not available. Set GOOGLE_PLACES_API_KEY (or VITE_GOOGLE_PLACES_API_KEY) in your env."
      );
      return;
    }

    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places`;
    script.async = true;
    script.defer = true;
    script.dataset.googlePlaces = "true";
    script.addEventListener("load", handleLoaded);
    document.head.appendChild(script);

    return () => {
      script.removeEventListener("load", handleLoaded);
    };
  }, [apiKey, id, name, onChange, setValue]);

  const setRefs = (el: HTMLInputElement | null) => {
    inputRef.current = el;
    if (typeof forwardedRef === "function") {
      forwardedRef(el);
    } else if (forwardedRef && "current" in (forwardedRef as any)) {
      (forwardedRef as React.MutableRefObject<HTMLInputElement | null>).current =
        el;
    }
  };

  return (
    <Input
      ref={setRefs}
      id={id}
      name={name}
      value={value}
      onChange={onChange}
      onBlur={onBlur}
      {...rest}
    />
  );
});

GoogleAddressInput.displayName = "GoogleAddressInput";

export default GoogleAddressInput;
