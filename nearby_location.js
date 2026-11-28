export default function ({data, parentElement, setTriggerValue}) {
  const button = parentElement.querySelector("button");
  const status = parentElement.querySelector("[role=status]");
  button.textContent = data.button;
  button.title = data.privacy;
  button.dataset.origin = data.origin;
  button.onclick = () => {
    const origin = button.dataset.origin;
    button.disabled = true;
    status.textContent = data.working;
    const finish = result => {
      if (!button.isConnected) return;
      button.disabled = false;
      status.textContent = "";
      if (origin === button.dataset.origin) setTriggerValue("result", result);
    };
    if (!navigator.geolocation) {
      finish({unavailable: true});
      return;
    }
    try {
      navigator.geolocation.getCurrentPosition(
        ({coords}) => finish({
          lat: Math.round(coords.latitude * 1000) / 1000,
          lon: Math.round(coords.longitude * 1000) / 1000
        }),
        () => finish({unavailable: true}),
        {enableHighAccuracy: false, maximumAge: 120000, timeout: 10000}
      );
    } catch {
      finish({unavailable: true});
    }
  };
}
