// /family was renamed Circles (support is for friends too, not only family). Old links still land.
import { Redirect } from 'expo-router';

export default function FamilyRedirect() {
  return <Redirect href="/circles" />;
}
