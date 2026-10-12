import type { DayPlan } from "../../api/client";

/** One card per day of a plan. Every value is shown as the API gives it; nothing is parsed. */
export function PlanCards({ plan }: { plan: DayPlan[] }) {
  return (
    <ul className="plan" aria-label="Plan">
      {plan.map((day) => (
        <li key={day.day}>
          <article className="day-card" aria-label={`Day ${day.day}`}>
            <h3>Day {day.day}</h3>
            <dl>
              <dt>Current city</dt>
              <dd>{day.current_city}</dd>
              <dt>Transportation</dt>
              <dd>{day.transportation}</dd>
              <dt>Breakfast</dt>
              <dd>{day.breakfast}</dd>
              <dt>Attractions</dt>
              <dd>
                {day.attractions.length === 0 ? (
                  "-"
                ) : (
                  <ul className="attractions">
                    {day.attractions.map((attraction, index) => (
                      <li key={index}>{attraction}</li>
                    ))}
                  </ul>
                )}
              </dd>
              <dt>Lunch</dt>
              <dd>{day.lunch}</dd>
              <dt>Dinner</dt>
              <dd>{day.dinner}</dd>
              <dt>Accommodation</dt>
              <dd>{day.accommodation}</dd>
            </dl>
          </article>
        </li>
      ))}
    </ul>
  );
}
